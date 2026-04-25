"""
Flow: pre-seeded plan blocks -> OpenSCAD agent -> compilable 3D model script

NOTE: Frontend integration of this flow is not yet implemented; the backend
endpoint is fully functional and tested here.

Run from api/:
    uv run tests/test_plan_to_model.py
"""

import os
import sys

import httpx

BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

BLOCKS = [
    {
        "content": {
            "block_type": "objective",
            "goal_statement": "Waterproof enclosure for Arduino Mega and LiPo battery pack",
            "success_criteria": [
                "Board sits flat on standoffs with USB-B and power jack exposed",
                "Lid can be removed with 4 screws",
            ],
        },
        "reasoning": "Defined by team at the start of the meeting as primary build goal",
    },
    {
        "content": {
            "block_type": "variable",
            "parameter_name": "Board Length",
            "value": 102.0,
            "unit": "mm",
            "is_locked": True,
        },
        "reasoning": "Standard Arduino Mega 2560 footprint, explicitly confirmed by team",
    },
    {
        "content": {
            "block_type": "variable",
            "parameter_name": "Board Width",
            "value": 54.0,
            "unit": "mm",
            "is_locked": True,
        },
        "reasoning": "Standard Arduino Mega 2560 footprint, explicitly confirmed by team",
    },
    {
        "content": {
            "block_type": "variable",
            "parameter_name": "Wall Thickness",
            "value": 5.0,
            "unit": "mm",
            "is_locked": True,
        },
        "reasoning": "Team locked this in; needed to clear USB-B connector housing",
    },
    {
        "content": {
            "block_type": "decision",
            "final_choice": "Ventilation slots on top face",
            "rejected_alternatives": ["No ventilation", "Side-mounted fan cutout"],
        },
        "reasoning": "Team agreed on passive ventilation slots after rejecting fan cutout due to space constraints",
    },
    {
        "content": {
            "block_type": "missing_info",
            "blocking_parameter": "Battery Thickness",
            "impact": "Cannot determine enclosure height until battery thickness is confirmed by supplier",
        },
        "reasoning": "Supplier has not confirmed LiPo pack dimensions; blocks final Z dimension",
    },
]

OPENSCAD_KEYWORDS = {"cube", "cylinder", "sphere", "difference", "union", "translate", "rotate", "linear_extrude"}


def check(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)


def run() -> None:
    client = httpx.Client(base_url=BASE_URL, timeout=180)

    # 1. Create meeting
    r = client.post("/api/meetings", json={})
    check(r.status_code == 201, f"create meeting: {r.status_code} {r.text}")
    meeting_id = r.json()["id"]
    print(f"  meeting: {meeting_id}")

    # 2. Seed plan blocks
    for block in BLOCKS:
        r = client.post(f"/api/meetings/{meeting_id}/blocks", json=block)
        check(r.status_code == 201, f"create block: {r.status_code} {r.text}")
    print(f"  blocks: {len(BLOCKS)} seeded")

    # 3. Run OpenSCAD agent
    print("  running OpenSCAD agent (this may take a moment)...")
    r = client.post(f"/api/meetings/{meeting_id}/agent/model", params={"provider": "pydantic"})
    check(r.status_code == 200, f"trigger model agent: {r.status_code} {r.text}")

    result = r.json()
    check("iteration" in result, "response missing 'iteration'")
    check("meta" in result, "response missing 'meta'")

    iteration = result["iteration"]
    check("id" in iteration, "iteration missing 'id'")
    check("script" in iteration, "iteration missing 'script'")
    check("reasoning" in iteration, "iteration missing 'reasoning'")

    script: str = iteration["script"]
    check(isinstance(script, str) and len(script) >= 10, "script is empty or too short")
    check(not script.strip().startswith("```"), "script contains markdown fences")

    found_keywords = [kw for kw in OPENSCAD_KEYWORDS if kw in script]
    check(len(found_keywords) > 0, f"script contains no OpenSCAD primitives (checked: {OPENSCAD_KEYWORDS})")

    # 4. Print result
    print(f"\n  keywords found: {found_keywords}")
    print(f"  reasoning: {iteration['reasoning'][:120]}...")
    print(f"\n--- OpenSCAD script ({len(script)} chars) ---")
    print(script)
    print("---")
    print(f"\n  meta: {result['meta']['provider']} | {result['meta']['latency_ms']}ms")


if __name__ == "__main__":
    try:
        run()
        print("\n[PASS] plan -> 3d model")
    except AssertionError as e:
        print(f"\n[FAIL] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FAIL] unexpected error: {e}")
        sys.exit(1)
