"""
Retrieve and print all MuBit memories for the QuakkaCad project.

Run from api/:
    uv run tests/test_mubit_memories.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

MUBIT_API_KEY = os.getenv("MUBIT_API_KEY", "")
TEMPLATE_LIBRARY_RUN_ID = "quakkacad:template-library:v1"


def get_client():
    if not MUBIT_API_KEY:
        print("ERROR: MUBIT_API_KEY not set")
        sys.exit(1)
    from mubit import Client
    return Client()


def section(title: str):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")


def dump(obj):
    try:
        print(json.dumps(obj, indent=2, default=str))
    except Exception:
        print(repr(obj))


def run_sync(client, method_name, **kwargs):
    fn = getattr(client, method_name)
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, lambda: fn(**kwargs))


async def call(client, method_name, **kwargs):
    fn = getattr(client, method_name)
    return await asyncio.get_event_loop().run_in_executor(None, lambda: fn(**kwargs))


async def main():
    client = get_client()

    # ------------------------------------------------------------------
    # 1. get_context with generous budget
    # ------------------------------------------------------------------
    section(f"get_context (budget=2000): session={TEMPLATE_LIBRARY_RUN_ID}")
    try:
        result = await call(client, "get_context",
            session_id=TEMPLATE_LIBRARY_RUN_ID,
            query="gear train with 3 gears",
            mode="summary",
            max_token_budget=2000,
        )
        print(f"context_block length: {len(result.get('context_block', ''))}")
        print(f"budget_used: {result.get('budget_used')}  budget_remaining: {result.get('budget_remaining')}")
        print(f"source_counts: {result.get('source_counts_by_entry_type')}")
        cb = result.get("context_block", "")
        if cb:
            print(f"\ncontext_block:\n{cb}")
        else:
            print("\nsection_summaries:")
            for s in result.get("section_summaries") or []:
                print(f"  [{s.get('section_name')}] {s.get('item_count')} items")
                print(f"    preview: {s.get('top_item_preview', '')[:200]}")
    except Exception as ex:
        print(f"ERROR: {ex}")

    # ------------------------------------------------------------------
    # 2. lessons — list stored lessons
    # ------------------------------------------------------------------
    section(f"lessons: session={TEMPLATE_LIBRARY_RUN_ID}")
    try:
        result = await call(client, "lessons", session_id=TEMPLATE_LIBRARY_RUN_ID)
        dump(result)
    except Exception as ex:
        print(f"ERROR: {ex}")

    # ------------------------------------------------------------------
    # 3. recall — semantic recall
    # ------------------------------------------------------------------
    section(f"recall: session={TEMPLATE_LIBRARY_RUN_ID}")
    try:
        result = await call(client, "recall",
            session_id=TEMPLATE_LIBRARY_RUN_ID,
            query="what templates are available?",
        )
        dump(result)
    except Exception as ex:
        print(f"ERROR: {ex}")

    # ------------------------------------------------------------------
    # 4. get_run_history
    # ------------------------------------------------------------------
    section(f"get_run_history: session={TEMPLATE_LIBRARY_RUN_ID}")
    try:
        result = await call(client, "get_run_history", run_id=TEMPLATE_LIBRARY_RUN_ID)
        dump(result)
    except Exception as ex:
        print(f"ERROR: {ex}")

    # ------------------------------------------------------------------
    # 5. query
    # ------------------------------------------------------------------
    section(f"query: session={TEMPLATE_LIBRARY_RUN_ID}")
    try:
        result = await call(client, "query",
            session_id=TEMPLATE_LIBRARY_RUN_ID,
            query="what templates are available?",
        )
        dump(result)
    except Exception as ex:
        print(f"ERROR: {ex}")


if __name__ == "__main__":
    asyncio.run(main())
