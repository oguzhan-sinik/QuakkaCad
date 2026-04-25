"""BFF routes: conference management, ElevenLabs token proxy, and WebRTC signaling."""
from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Optional

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

router = APIRouter(tags=["bff"])

# ---------------------------------------------------------------------------
# Conference ID
# ---------------------------------------------------------------------------

_CONF_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"


def _generate_conference_id() -> str:
    raw = secrets.token_bytes(8)
    return "".join(_CONF_CHARS[b % len(_CONF_CHARS)] for b in raw)


@router.post("/api/conference", tags=["conference"])
async def create_conference():
    return {"conferenceId": _generate_conference_id()}


# ---------------------------------------------------------------------------
# ElevenLabs single-use token proxy
# ---------------------------------------------------------------------------


@router.get("/api/token", tags=["conference"])
async def get_elevenlabs_token():
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        return JSONResponse({"error": "ELEVENLABS_API_KEY not configured"}, status_code=500)

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.post(
                "https://api.elevenlabs.io/v1/single-use-token/realtime_scribe",
                headers={"xi-api-key": api_key},
            )
        except Exception as e:
            return JSONResponse({"error": f"Failed to fetch token: {e}"}, status_code=502)

    if res.is_error:
        return JSONResponse(
            {"error": f"ElevenLabs token error: {res.status_code} {res.text}"},
            status_code=502,
        )

    try:
        return {"token": res.json()["token"]}
    except Exception:
        return JSONResponse(
            {"error": f"Unexpected ElevenLabs response: {res.text[:200]}"},
            status_code=502,
        )


# ---------------------------------------------------------------------------
# WebRTC signaling (port of server.mjs)
# ---------------------------------------------------------------------------


@dataclass
class _Peer:
    ws: WebSocket
    name: str = "Anonymous"
    muted: bool = False


_rooms: dict[str, dict[str, _Peer]] = {}
_transcripts: dict[str, list[dict]] = {}


async def _broadcast(room: dict[str, _Peer], exclude_peer_id: Optional[str], msg: dict) -> None:
    data = json.dumps(msg)
    for pid, peer in list(room.items()):
        if pid != exclude_peer_id:
            try:
                await peer.ws.send_text(data)
            except Exception:
                pass


@router.websocket("/ws/{conference_id}")
async def signaling_ws(ws: WebSocket, conference_id: str):
    await ws.accept()

    peer_id = secrets.token_hex(8)
    peer_name = "Anonymous"

    room = _rooms.setdefault(conference_id, {})

    try:
        while True:
            try:
                raw = await ws.receive_text()
                msg = json.loads(raw)
            except (ValueError, KeyError):
                continue

            msg_type = msg.get("type")

            if msg_type == "join":
                peer_name = msg.get("name", "Anonymous")
                room[peer_id] = _Peer(ws=ws, name=peer_name, muted=False)

                await ws.send_text(json.dumps({
                    "type": "joined",
                    "peerId": peer_id,
                    "peers": [
                        {"peerId": pid, "name": p.name, "muted": p.muted}
                        for pid, p in room.items()
                        if pid != peer_id
                    ],
                }))

                await _broadcast(room, peer_id, {
                    "type": "peer-joined",
                    "peerId": peer_id,
                    "name": peer_name,
                })

            elif msg_type in ("offer", "answer", "ice-candidate"):
                target = room.get(msg.get("to", ""))
                if target:
                    await target.ws.send_text(json.dumps({
                        "type": msg_type,
                        "from": peer_id,
                        "sdp": msg.get("sdp"),
                        "candidate": msg.get("candidate"),
                    }))

            elif msg_type == "mute-status":
                if peer_id in room:
                    room[peer_id].muted = bool(msg.get("muted", False))
                await _broadcast(room, peer_id, {
                    "type": "mute-status",
                    "peerId": peer_id,
                    "muted": msg.get("muted", False),
                })

            elif msg_type == "transcript":
                timestamp = msg.get("timestamp") or int(time.time() * 1000)
                transcript_msg = {
                    "type": "transcript",
                    "peerId": peer_id,
                    "speakerName": peer_name,
                    "text": msg.get("text", ""),
                    "isPartial": msg.get("isPartial", False),
                    "timestamp": timestamp,
                }

                if not msg.get("isPartial") and msg.get("text"):
                    _transcripts.setdefault(conference_id, []).append({
                        "speakerName": peer_name,
                        "text": msg["text"],
                        "timestamp": timestamp,
                    })

                await _broadcast(room, None, transcript_msg)

            elif msg_type == "plan-update":
                await _broadcast(room, peer_id, {
                    "type": "plan-update",
                    "blocks": msg.get("blocks", []),
                })

    except WebSocketDisconnect:
        pass
    finally:
        room.pop(peer_id, None)
        await _broadcast(room, None, {"type": "peer-left", "peerId": peer_id})
        if not room:
            _rooms.pop(conference_id, None)
