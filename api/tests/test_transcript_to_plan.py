"""
Flow: transcript entries -> planner agent -> structured plan blocks

Run from api/:
    uv run tests/test_transcript_to_plan.py
"""

import json
import os
import sys

import httpx

BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

TRANSCRIPT = [
    {"text": "We need an enclosure for our Arduino Mega and a 3.7V LiPo battery pack.", "start_time": 0.0, "end_time": 4.2},
    {"text": "The board footprint is 102mm by 54mm, that's the standard Mega size.", "start_time": 4.5, "end_time": 9.1},
    {"text": "Let's lock in 5mm wall thickness — thick enough for the connectors.", "start_time": 9.3, "end_time": 13.8},
    {"text": "We should add ventilation holes on the top face for heat dissipation.", "start_time": 14.0, "end_time": 18.6},
    {"text": "We still haven't decided the battery dimensions — do we know the thickness?", "start_time": 19.0, "end_time": 24.3},
    {"text": "No, the battery supplier hasn't confirmed spec yet. That's a blocker.", "start_time": 24.6, "end_time": 28.0},
]

VALID_BLOCK_TYPES = {"objective", "variable", "decision", "missing_info"}


def check(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)


def run() -> None:
    client = httpx.Client(base_url=BASE_URL, timeout=120)

    # 1. Create meeting
    r = client.post("/api/meetings", json={})
    check(r.status_code == 201, f"create meeting: {r.status_code} {r.text}")
    meeting_id = r.json()["id"]
    print(f"  meeting: {meeting_id}")

    # 2. Seed transcript
    for entry in TRANSCRIPT:
        r = client.post(f"/api/meetings/{meeting_id}/transcript", json=entry)
        check(r.status_code == 201, f"add transcript entry: {r.status_code} {r.text}")
    print(f"  transcript: {len(TRANSCRIPT)} entries posted")

    # 3. Run planner agent
    print("  running planner agent (this may take a moment)...")
    r = client.post(f"/api/meetings/{meeting_id}/agent/plan", params={"provider": "pydantic"})
    check(r.status_code == 200, f"trigger planner: {r.status_code} {r.text}")

    result = r.json()
    check("created" in result, "response missing 'created'")
    check("updated" in result, "response missing 'updated'")
    check("meta" in result, "response missing 'meta'")
    check(isinstance(result["created"], list), "'created' is not a list")
    check(isinstance(result["updated"], list), "'updated' is not a list")

    # 4. Validate each block
    all_blocks = result["created"] + result["updated"]
    check(len(all_blocks) > 0, "agent returned no blocks")

    for block in all_blocks:
        check("id" in block, "block missing 'id'")
        check("status" in block, "block missing 'status'")
        check("version" in block, "block missing 'version'")
        check("reasoning" in block, "block missing 'reasoning'")
        check(len(block["reasoning"]) >= 10, f"reasoning too short: {block['reasoning']!r}")
        check("content" in block, "block missing 'content'")
        bt = block["content"].get("block_type")
        check(bt in VALID_BLOCK_TYPES, f"unknown block_type: {bt!r}")

    # 5. Print summary
    print(f"\n  blocks created: {len(result['created'])}, updated: {len(result['updated'])}")
    for b in result["created"]:
        bt = b["content"]["block_type"]
        label = {
            "objective": b["content"].get("goal_statement", ""),
            "variable": f"{b['content'].get('parameter_name')} = {b['content'].get('value')} {b['content'].get('unit')}",
            "decision": b["content"].get("final_choice", ""),
            "missing_info": b["content"].get("blocking_parameter", ""),
        }.get(bt, "")
        locked = " [LOCKED]" if bt == "variable" and b["content"].get("is_locked") else ""
        print(f"    [{bt}]{locked} {label}")

    print(f"\n  meta: {result['meta']['provider']} | {result['meta']['latency_ms']}ms")


if __name__ == "__main__":
    try:
        run()
        print("\n[PASS] transcript -> plan")
    except AssertionError as e:
        print(f"\n[FAIL] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FAIL] unexpected error: {e}")
        sys.exit(1)
