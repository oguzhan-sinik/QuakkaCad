from __future__ import annotations

import asyncio
import json
from enum import Enum
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import logging

from agents import run_openscad_edit, run_openscad_fix, run_openscad_meeting, run_planner_chunked
from openscad_compiler import compile_openscad
from schemas import (
    Meeting,
    MeetingCreate,
    MeetingState,
    ModelDelta,
    ModelIteration,
    ModelIterationCreate,
    PlanBlock,
    PlanBlockCreate,
    TranscriptEntry,
    TranscriptEntryCreate,
)
from storage import store

router = APIRouter(prefix="/api", tags=["meetings"])
logger = logging.getLogger(__name__)


def _get_meeting_or_404(meeting_id: UUID) -> Meeting:
    try:
        return store.require_meeting(meeting_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found")


class ProviderEnum(str, Enum):
    groq = "groq"


# ---------------------------------------------------------------------------
# Meetings
# ---------------------------------------------------------------------------


@router.post("/meetings", response_model=Meeting, status_code=status.HTTP_201_CREATED, tags=["meetings"])
def create_meeting(body: MeetingCreate = MeetingCreate()):  # type: ignore[assignment]
    meeting = Meeting(title=body.title)
    store.meetings[meeting.id] = meeting
    store.transcripts[meeting.id] = []
    store.blocks[meeting.id] = []
    store.models[meeting.id] = []
    store.processed_counts[meeting.id] = 0
    store.model_block_snapshots[meeting.id] = set()
    return meeting


@router.get("/meetings/{meeting_id}/state", response_model=MeetingState, tags=["meetings"])
def get_meeting_state(meeting_id: UUID):
    meeting = _get_meeting_or_404(meeting_id)
    return MeetingState(
        meeting=meeting,
        transcript=store.transcripts[meeting_id],
        blocks=store.blocks[meeting_id],
        models=store.models[meeting_id],
    )


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------


@router.post(
    "/meetings/{meeting_id}/transcript",
    response_model=TranscriptEntry,
    status_code=status.HTTP_201_CREATED,
    tags=["transcript"],
)
def add_transcript_entry(meeting_id: UUID, body: TranscriptEntryCreate):
    _get_meeting_or_404(meeting_id)
    entry = TranscriptEntry(**body.model_dump())
    store.transcripts[meeting_id].append(entry)
    return entry


# ---------------------------------------------------------------------------
# Plan Blocks
# ---------------------------------------------------------------------------


@router.get("/meetings/{meeting_id}/blocks", response_model=list[PlanBlock], tags=["blocks"])
def list_blocks(meeting_id: UUID):
    _get_meeting_or_404(meeting_id)
    return store.blocks[meeting_id]


@router.post(
    "/meetings/{meeting_id}/blocks",
    response_model=PlanBlock,
    status_code=status.HTTP_201_CREATED,
    tags=["blocks"],
)
def create_block(meeting_id: UUID, body: PlanBlockCreate):
    _get_meeting_or_404(meeting_id)
    block = PlanBlock(**body.model_dump())
    store.blocks[meeting_id].append(block)
    store.block_index[block.id] = meeting_id
    return block


@router.put("/blocks/{block_id}", response_model=PlanBlock, tags=["blocks"])
def update_block(block_id: UUID, body: PlanBlock):
    meeting_id = store.block_index.get(block_id)
    if meeting_id is None:
        raise HTTPException(status_code=404, detail=f"Block {block_id} not found")
    blocks = store.blocks[meeting_id]
    for i, b in enumerate(blocks):
        if b.id == block_id:
            updated = body.model_copy(update={"id": block_id})
            blocks[i] = updated
            return updated
    raise HTTPException(status_code=404, detail=f"Block {block_id} not found")


# ---------------------------------------------------------------------------
# CAD Models
# ---------------------------------------------------------------------------


@router.get("/meetings/{meeting_id}/models/latest", response_model=ModelIteration, tags=["models"])
def get_latest_model(meeting_id: UUID):
    _get_meeting_or_404(meeting_id)
    models = store.models[meeting_id]
    if not models:
        raise HTTPException(status_code=404, detail="No model iterations for this meeting")
    return models[-1]


@router.post(
    "/meetings/{meeting_id}/models",
    response_model=ModelIteration,
    status_code=status.HTTP_201_CREATED,
    tags=["models"],
)
def create_model_iteration(meeting_id: UUID, body: ModelIterationCreate):
    _get_meeting_or_404(meeting_id)
    iteration = ModelIteration(**body.model_dump())
    store.models[meeting_id].append(iteration)
    return iteration


# ---------------------------------------------------------------------------
# Agent triggers
# ---------------------------------------------------------------------------


class OpenSCADResult(BaseModel):
    iteration: ModelIteration
    meta: dict


@router.post("/meetings/{meeting_id}/agent/plan", tags=["agents"])
async def trigger_planner(
    meeting_id: UUID,
    provider: ProviderEnum = Query(default=ProviderEnum.groq),
    temperature: float = Query(default=0.3, ge=0.0, le=2.0),
    max_tokens: int = Query(default=4096, ge=256, le=16384),
):
    """Stream planner results as SSE events, one transcript chunk at a time."""
    _get_meeting_or_404(meeting_id)

    all_entries = store.transcripts[meeting_id]
    existing_blocks = list(store.blocks[meeting_id])
    prev_count = store.processed_counts.get(meeting_id, 0)
    new_entries = all_entries[prev_count:]

    if not new_entries:
        async def _empty():
            yield f"data: {json.dumps({'type': 'done', 'total_created': 0, 'total_updated': 0})}\n\n"
        return StreamingResponse(
            _empty(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def event_stream():
        total_created = 0
        total_updated = 0

        try:
            async for etype, payload in run_planner_chunked(
                transcript=new_entries,
                existing_blocks=existing_blocks,
                provider=provider.value,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                if etype == "chunk_start":
                    yield f"data: {json.dumps({'type': 'chunk_start', 'prev_count': prev_count, **payload})}\n\n"

                elif etype == "chunk_result":
                    output = payload

                    for block_create in output.blocks_to_create:
                        block = PlanBlock(**block_create.model_dump())
                        store.blocks[meeting_id].append(block)
                        store.block_index[block.id] = meeting_id
                        total_created += 1
                        yield f"data: {json.dumps({'type': 'block_created', 'block': json.loads(block.model_dump_json())})}\n\n"

                    for block_update in output.blocks_to_update:
                        bid = block_update.id
                        mid = store.block_index.get(bid)
                        if mid != meeting_id:
                            continue
                        for i, b in enumerate(store.blocks[meeting_id]):
                            if b.id == bid:
                                store.blocks[meeting_id][i] = block_update
                                total_updated += 1
                                yield f"data: {json.dumps({'type': 'block_updated', 'block': json.loads(block_update.model_dump_json())})}\n\n"
                                break

                elif etype == "chunk_complete":
                    yield f"data: {json.dumps({'type': 'chunk_complete', **payload})}\n\n"

                elif etype == "error":
                    yield f"data: {json.dumps({'type': 'error', **payload})}\n\n"
                    return

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"
            return

        store.processed_counts[meeting_id] = len(all_entries)
        logger.info(
            "plan generation complete for meeting %s: %d created, %d updated",
            meeting_id, total_created, total_updated,
        )
        yield f"data: {json.dumps({'type': 'done', 'total_created': total_created, 'total_updated': total_updated})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/meetings/{meeting_id}/agent/model", response_model=OpenSCADResult, tags=["agents"])
async def trigger_openscad(
    meeting_id: UUID,
    provider: ProviderEnum = Query(default=ProviderEnum.groq),
    temperature: float = Query(default=0.5, ge=0.0, le=2.0),
    max_tokens: int = Query(default=8192, ge=256, le=16384),
    max_fix_iterations: int = Query(default=3, ge=0, le=5),
):
    """Run the OpenSCAD Agent, compile the result, and iterate fixes until clean."""
    _get_meeting_or_404(meeting_id)

    current_models = store.models[meeting_id]
    current_blocks = store.blocks[meeting_id]
    latest_model = current_models[-1] if current_models else None

    try:
        if latest_model is None:
            # First generation — full synthesis
            iteration_create, meta = await run_openscad_meeting(
                transcript=store.transcripts[meeting_id],
                blocks=current_blocks,
                provider=provider.value,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            delta = ModelDelta(changed_block_ids=[], edits=[], is_full_regen=True)
        else:
            # Incremental edit — only pass blocks that changed since last model run
            prev_block_ids: set[UUID] = store.model_block_snapshots.get(meeting_id, set())
            changed_blocks = [
                b for b in current_blocks
                if b.version > 1 or b.id not in prev_block_ids
            ]
            if not changed_blocks:
                changed_blocks = list(current_blocks)

            patched_script, edits, meta = await run_openscad_edit(
                current_script=latest_model.script,
                changed_blocks=changed_blocks,
                provider=provider.value,
                max_tokens=max_tokens,
            )
            iteration_create = ModelIterationCreate(
                script=patched_script,
                reasoning=meta.get("reasoning", "incremental edit"),
                applied_lessons=[],
            )
            delta = ModelDelta(
                changed_block_ids=[b.id for b in changed_blocks],
                edits=edits,
                is_full_regen=False,
            )

    except asyncio.CancelledError:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Agent error: {e}")

    # --- Compile + fix loop ---
    compile_ok: bool | None = None
    compile_stderr: str | None = None
    fix_iterations = 0
    script = iteration_create.script

    if max_fix_iterations > 0:
        try:
            ok, stderr = await compile_openscad(script)
            compile_ok = ok
            compile_stderr = stderr or None

            for _ in range(max_fix_iterations):
                if ok:
                    break
                errors = [l for l in stderr.splitlines() if l.startswith("ERROR:")]
                if not errors:
                    break
                fixed, _ = await run_openscad_fix(
                    current_script=script,
                    stderr=stderr,
                    provider=provider.value,
                    max_tokens=max_tokens,
                )
                fix_iterations += 1
                script = fixed
                ok, stderr = await compile_openscad(script)
                compile_ok = ok
                compile_stderr = stderr or None

            iteration_create = ModelIterationCreate(
                script=script,
                reasoning=iteration_create.reasoning,
                applied_lessons=iteration_create.applied_lessons,
            )
        except FileNotFoundError as e:
            logger.warning("OpenSCAD not available — skipping compile loop: %s", e)

    iteration = ModelIteration(
        **iteration_create.model_dump(),
        delta=delta,
        compile_ok=compile_ok,
        compile_stderr=compile_stderr,
        fix_iterations=fix_iterations,
    )
    store.models[meeting_id].append(iteration)
    store.model_block_snapshots[meeting_id] = {b.id for b in current_blocks}

    meta["compile_ok"] = compile_ok
    meta["fix_iterations"] = fix_iterations
    logger.info(
        "model generation complete for meeting %s: %d fix attempt(s), compile_ok=%s",
        meeting_id, fix_iterations, compile_ok,
    )
    return OpenSCADResult(iteration=iteration, meta=meta)
