from __future__ import annotations

from enum import Enum
from uuid import UUID

import asyncio

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from agents import run_openscad_meeting, run_planner
from schemas import (
    Meeting,
    MeetingCreate,
    MeetingState,
    ModelIteration,
    ModelIterationCreate,
    PlanBlock,
    PlanBlockCreate,
    TranscriptEntry,
    TranscriptEntryCreate,
)
from storage import store

router = APIRouter(prefix="/api", tags=["meetings"])


def _get_meeting_or_404(meeting_id: UUID) -> Meeting:
    try:
        return store.require_meeting(meeting_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found")


class ProviderEnum(str, Enum):
    pydantic = "pydantic"
    pydantic_fast = "pydantic-fast"


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


class PlannerResult(BaseModel):
    created: list[PlanBlock]
    updated: list[PlanBlock]
    meta: dict


class OpenSCADResult(BaseModel):
    iteration: ModelIteration
    meta: dict


@router.post("/meetings/{meeting_id}/agent/plan", response_model=PlannerResult, tags=["agents"])
async def trigger_planner(
    meeting_id: UUID,
    provider: ProviderEnum = Query(default=ProviderEnum.pydantic_fast),
    temperature: float = Query(default=0.3, ge=0.0, le=2.0),
    max_tokens: int = Query(default=4096, ge=256, le=16384),
):
    """Run the Planner Agent against the current transcript and return created/updated blocks."""
    _get_meeting_or_404(meeting_id)

    try:
        output, meta = await run_planner(
            transcript=store.transcripts[meeting_id],
            existing_blocks=store.blocks[meeting_id],
            provider=provider.value,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except asyncio.CancelledError:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Agent error: {e}")

    created: list[PlanBlock] = []
    for block_create in output.blocks_to_create:
        block = PlanBlock(**block_create.model_dump())
        store.blocks[meeting_id].append(block)
        store.block_index[block.id] = meeting_id
        created.append(block)

    updated: list[PlanBlock] = []
    for block_update in output.blocks_to_update:
        bid = block_update.id
        mid = store.block_index.get(bid)
        if mid != meeting_id:
            continue
        for i, b in enumerate(store.blocks[meeting_id]):
            if b.id == bid:
                store.blocks[meeting_id][i] = block_update
                updated.append(block_update)
                break

    return PlannerResult(created=created, updated=updated, meta=meta)


@router.post("/meetings/{meeting_id}/agent/model", response_model=OpenSCADResult, tags=["agents"])
async def trigger_openscad(
    meeting_id: UUID,
    provider: ProviderEnum = Query(default=ProviderEnum.pydantic),
    temperature: float = Query(default=0.5, ge=0.0, le=2.0),
    max_tokens: int = Query(default=8192, ge=256, le=16384),
):
    """Run the OpenSCAD Agent and save the resulting model iteration."""
    _get_meeting_or_404(meeting_id)

    try:
        iteration_create, meta = await run_openscad_meeting(
            transcript=store.transcripts[meeting_id],
            blocks=store.blocks[meeting_id],
            provider=provider.value,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except asyncio.CancelledError:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Agent error: {e}")

    iteration = ModelIteration(**iteration_create.model_dump())
    store.models[meeting_id].append(iteration)

    return OpenSCADResult(iteration=iteration, meta=meta)
