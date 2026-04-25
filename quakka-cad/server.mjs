import { WebSocketServer } from "ws";
import { randomBytes } from "crypto";

const PORT = 3001;
const rooms = new Map(); // conferenceId -> Map(peerId -> {ws, name, muted})
const transcripts = new Map(); // conferenceId -> TranscriptLine[]

const wss = new WebSocketServer({ port: PORT });

wss.on("connection", (ws, req) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const conferenceId = url.pathname.slice(1); // /<conferenceId>

  if (!conferenceId) {
    ws.close(4000, "Missing conference ID");
    return;
  }

  const peerId = randomBytes(8).toString("hex");
  let peerName = "Anonymous";

  if (!rooms.has(conferenceId)) {
    rooms.set(conferenceId, new Map());
  }
  const room = rooms.get(conferenceId);

  ws.on("message", (data) => {
    try {
      const msg = JSON.parse(data);

      switch (msg.type) {
        case "join": {
          peerName = msg.name || "Anonymous";
          room.set(peerId, { ws, name: peerName, muted: false });

          // Send the joiner their own ID and the current peer list
          ws.send(
            JSON.stringify({
              type: "joined",
              peerId,
              peers: Array.from(room.entries())
                .filter(([id]) => id !== peerId)
                .map(([id, p]) => ({
                  peerId: id,
                  name: p.name,
                  muted: p.muted,
                })),
            })
          );

          // Notify others
          broadcast(room, peerId, {
            type: "peer-joined",
            peerId,
            name: peerName,
          });
          break;
        }

        case "offer":
        case "answer":
        case "ice-candidate": {
          const target = room.get(msg.to);
          if (target) {
            target.ws.send(
              JSON.stringify({
                type: msg.type,
                from: peerId,
                sdp: msg.sdp,
                candidate: msg.candidate,
              })
            );
          }
          break;
        }

        case "mute-status": {
          const peer = room.get(peerId);
          if (peer) peer.muted = msg.muted;
          broadcast(room, peerId, {
            type: "mute-status",
            peerId,
            muted: msg.muted,
          });
          break;
        }

        case "transcript": {
          // Fan out transcript events to all participants
          const transcriptMsg = {
            type: "transcript",
            peerId,
            speakerName: peerName,
            text: msg.text,
            isPartial: msg.isPartial,
            timestamp: msg.timestamp || Date.now(),
          };

          // Store committed lines
          if (!msg.isPartial && msg.text) {
            if (!transcripts.has(conferenceId)) {
              transcripts.set(conferenceId, []);
            }
            transcripts.get(conferenceId).push({
              speakerName: peerName,
              text: msg.text,
              timestamp: transcriptMsg.timestamp,
            });
          }

          // Broadcast to ALL participants (including sender, so they see their own transcript)
          broadcast(room, null, transcriptMsg);
          break;
        }
      }
    } catch {
      // ignore malformed messages
    }
  });

  ws.on("close", () => {
    room.delete(peerId);
    broadcast(room, null, {
      type: "peer-left",
      peerId,
    });
    if (room.size === 0) {
      rooms.delete(conferenceId);
      // Keep transcripts for 1 hour after room closes for download
      setTimeout(() => transcripts.delete(conferenceId), 60 * 60 * 1000);
      console.log(`Room ${conferenceId} removed (empty)`);
    }
  });
});

function broadcast(room, excludePeerId, msg) {
  const data = JSON.stringify(msg);
  for (const [id, peer] of room) {
    if (id !== excludePeerId && peer.ws.readyState === 1) {
      peer.ws.send(data);
    }
  }
}

console.log(`Signaling server running on ws://localhost:${PORT}`);
