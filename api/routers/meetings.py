from __future__ import annotations

import asyncio
import json
from enum import Enum
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import logging

from agents import (
    run_cadquery_fix,
    run_cadquery_meeting,
    run_fea_analysis,
    run_openscad_edit,
    run_openscad_fix,
    run_openscad_meeting,
    run_openscad_refine,
    run_planner_chunked,
)
from cadquery_compiler import compile_cadquery
from mubit_client import record_generation_outcome, reflect_on_session
from openscad_compiler import compile_openscad
from schemas import (
    FEAAnalysis,
    Meeting,
    MeetingCreate,
    MeetingState,
    ModelDelta,
    ModelIteration,
    ModelIterationCreate,
    PlanBlock,
    PlanBlockCreate,
    TechnicalDrawing,
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
    cerebras = "cerebras"


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
    provider: ProviderEnum = Query(default=ProviderEnum.cerebras),
    temperature: float = Query(default=0.3, ge=0.0, le=2.0),
    max_tokens: int = Query(default=12000, ge=256, le=32768),
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
                    logger.warning("planner error for meeting %s: %s", meeting_id, payload.get("detail"))
                    yield f"data: {json.dumps({'type': 'error', **payload})}\n\n"
                    return

        except Exception as e:
            logger.warning("planner unhandled error for meeting %s: %s", meeting_id, e, exc_info=True)
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
    provider: ProviderEnum = Query(default=ProviderEnum.cerebras),
    temperature: float = Query(default=0.5, ge=0.0, le=2.0),
    max_tokens: int = Query(default=16000, ge=256, le=32768),
    max_fix_iterations: int = Query(default=3, ge=0, le=5),
):
    """Run the OpenSCAD Agent, compile the result, and iterate fixes until clean."""
    _get_meeting_or_404(meeting_id)

    current_models = store.models[meeting_id]
    current_blocks = store.blocks[meeting_id]
    latest_model = current_models[-1] if current_models else None
    full_transcript = store.transcripts[meeting_id]

    try:
        if latest_model is None:
            # First generation — full synthesis
            iteration_create, meta = await run_openscad_meeting(
                transcript=full_transcript,
                blocks=current_blocks,
                provider=provider.value,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            delta = ModelDelta(changed_block_ids=[], edits=[], is_full_regen=True)
        else:
            # Determine which blocks changed since last model run
            prev_block_ids: set[UUID] = store.model_block_snapshots.get(meeting_id, set())
            changed_blocks = [
                b for b in current_blocks
                if b.version > 1 or b.id not in prev_block_ids
            ]
            if not changed_blocks:
                changed_blocks = list(current_blocks)

            # Structural changes (objective/decision) require full regen — search-and-replace
            # cannot express new geometry insertions. Parametric changes (variable/missing_info)
            # are safe to patch in-place.
            _STRUCTURAL = {"objective", "decision"}
            is_structural = any(b.content.block_type in _STRUCTURAL for b in changed_blocks)

            if is_structural:
                iteration_create, meta = await run_openscad_meeting(
                    transcript=full_transcript,
                    blocks=current_blocks,
                    provider=provider.value,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                delta = ModelDelta(
                    changed_block_ids=[b.id for b in changed_blocks],
                    edits=[],
                    is_full_regen=True,
                )
            else:
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

    session_id = meta.get("session_id")
    if session_id:
        asyncio.create_task(record_generation_outcome(
            session_id=session_id,
            success=bool(compile_ok),
            error_msg=compile_stderr,
        ))
        asyncio.create_task(reflect_on_session(session_id))

    logger.info(
        "model generation complete for meeting %s: %d fix attempt(s), compile_ok=%s",
        meeting_id, fix_iterations, compile_ok,
    )
    return OpenSCADResult(iteration=iteration, meta=meta)


@router.post("/meetings/{meeting_id}/agent/refine", response_model=OpenSCADResult, tags=["agents"])
async def trigger_refine(
    meeting_id: UUID,
    max_fix_iterations: int = Query(default=3, ge=0, le=5),
):
    """Run Claude Opus 4.7 with adaptive extended thinking to produce a quality OpenSCAD model."""
    _get_meeting_or_404(meeting_id)

    current_models = store.models[meeting_id]
    current_blocks = store.blocks[meeting_id]
    latest_model = current_models[-1] if current_models else None

    try:
        iteration_create, meta = await run_openscad_refine(
            blocks=current_blocks,
            current_script=latest_model.script if latest_model else None,
            previous_compile_ok=latest_model.compile_ok if latest_model else None,
            previous_compile_stderr=latest_model.compile_stderr if latest_model else None,
        )
    except asyncio.CancelledError:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Refine agent error: {e}")

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
                fixed, _ = await run_openscad_fix(current_script=script, stderr=stderr)
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

    delta = ModelDelta(changed_block_ids=[], edits=[], is_full_regen=True)
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

    session_id = meta.get("session_id")
    if session_id:
        asyncio.create_task(record_generation_outcome(
            session_id=session_id,
            success=bool(compile_ok),
            error_msg=compile_stderr,
        ))
        asyncio.create_task(reflect_on_session(session_id))

    logger.info(
        "refine complete for meeting %s: %d fix attempt(s), compile_ok=%s",
        meeting_id, fix_iterations, compile_ok,
    )
    return OpenSCADResult(iteration=iteration, meta=meta)


# ---------------------------------------------------------------------------
# CadQuery Model Generation
# ---------------------------------------------------------------------------


@router.post("/meetings/{meeting_id}/agent/cadquery", response_model=OpenSCADResult, tags=["agents"])
async def trigger_cadquery(
    meeting_id: UUID,
    max_fix_iterations: int = Query(default=3, ge=0, le=5),
):
    """Run the CadQuery Agent (Anthropic), compile, export STEP+STL, iterate fixes."""
    _get_meeting_or_404(meeting_id)

    current_blocks = store.blocks[meeting_id]
    full_transcript = store.transcripts[meeting_id]

    try:
        iteration_create, meta = await run_cadquery_meeting(
            transcript=full_transcript,
            blocks=current_blocks,
        )
    except asyncio.CancelledError:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"CadQuery agent error: {e}")

    # --- Compile + fix loop on backend ---
    compile_ok: bool | None = None
    compile_stderr: str | None = None
    stl_bytes: bytes | None = None
    step_bytes: bytes | None = None
    fix_iterations = 0
    script = iteration_create.script

    for attempt in range(max_fix_iterations + 1):
        try:
            cq_result = await compile_cadquery(script)
            compile_ok = cq_result.success
            compile_stderr = cq_result.stderr or None
            stl_bytes = cq_result.stl_bytes
            step_bytes = cq_result.step_bytes
            if cq_result.success:
                break
            if attempt < max_fix_iterations:
                fixed, _ = await run_cadquery_fix(current_script=script, stderr=cq_result.stderr)
                fix_iterations += 1
                script = fixed
        except Exception as e:
            logger.warning("CadQuery compile error: %s", e)
            compile_ok = False
            compile_stderr = str(e)
            break

    iteration_create = ModelIterationCreate(
        script=script,
        script_language="cadquery",
        reasoning=iteration_create.reasoning,
        applied_lessons=iteration_create.applied_lessons,
    )

    delta = ModelDelta(changed_block_ids=[], edits=[], is_full_regen=True)
    iteration = ModelIteration(
        **iteration_create.model_dump(),
        delta=delta,
        compile_ok=compile_ok,
        compile_stderr=compile_stderr,
        fix_iterations=fix_iterations,
    )
    store.models[meeting_id].append(iteration)

    meta["compile_ok"] = compile_ok
    meta["fix_iterations"] = fix_iterations

    import base64
    # STL for 3D preview
    if stl_bytes:
        meta["stl_base64"] = base64.b64encode(stl_bytes).decode()
    # STEP for engineering download
    if step_bytes:
        meta["step_base64"] = base64.b64encode(step_bytes).decode()

    logger.info(
        "CadQuery generation complete for meeting %s: %d fix attempt(s), compile_ok=%s, STEP=%d bytes",
        meeting_id, fix_iterations, compile_ok, len(step_bytes) if step_bytes else 0,
    )
    return OpenSCADResult(iteration=iteration, meta=meta)


# ---------------------------------------------------------------------------
# FEA Analysis
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Template Pipeline (Composable Mechanical Parts)
# ---------------------------------------------------------------------------


class TemplateRequest(BaseModel):
    prompt: str


@router.post("/meetings/{meeting_id}/agent/template", tags=["agents"])
async def trigger_template(meeting_id: UUID, body: TemplateRequest):
    """Fast template-based generation via Cerebras. Target: <8s e2e."""
    from templates.render import render_from_prompt

    _get_meeting_or_404(meeting_id)

    try:
        spec, scad_source, meta = await render_from_prompt(body.prompt)
    except Exception as e:
        logger.error("Template pipeline error: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Template pipeline error: {e}")

    iteration_create = ModelIterationCreate(
        script=scad_source,
        script_language="openscad",
        reasoning=f"Template: {spec.assembly_type} — {spec.reasoning}",
        applied_lessons=[],
    )

    delta = ModelDelta(changed_block_ids=[], edits=[], is_full_regen=True)
    iteration = ModelIteration(
        **iteration_create.model_dump(),
        delta=delta,
        compile_ok=None,  # frontend WASM compiles
        compile_stderr=None,
        fix_iterations=0,
    )
    store.models[meeting_id].append(iteration)

    logger.info(
        "Template generation complete for meeting %s: %s, %.0fms",
        meeting_id, spec.assembly_type, meta.get("latency_ms", 0),
    )
    return OpenSCADResult(iteration=iteration, meta=meta)


class FEAResult(BaseModel):
    analysis: FEAAnalysis
    meta: dict


@router.post("/meetings/{meeting_id}/agent/fea", response_model=FEAResult, tags=["agents"])
async def trigger_fea_analysis(meeting_id: UUID):
    """Run FEA-style structural analysis on the latest model iteration."""
    _get_meeting_or_404(meeting_id)

    current_models = store.models[meeting_id]
    if not current_models:
        raise HTTPException(status_code=400, detail="No model iterations yet — generate a 3D model first")

    latest_model = current_models[-1]
    current_blocks = store.blocks[meeting_id]

    try:
        analysis_dict, meta = await run_fea_analysis(
            script=latest_model.script,
            blocks=current_blocks,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"FEA agent error: {e}")

    analysis = FEAAnalysis(
        model_iteration_id=latest_model.id,
        summary=analysis_dict.get("summary", ""),
        stress_points=analysis_dict.get("stress_points", []),
        recommendations=analysis_dict.get("recommendations", []),
        material_notes=analysis_dict.get("material_notes", ""),
        safety_factor=analysis_dict.get("safety_factor"),
        load_cases=analysis_dict.get("load_cases", []),
        full_report=analysis_dict.get("full_report", ""),
        stress_script=analysis_dict.get("stress_script", ""),
    )

    logger.info("FEA analysis complete for meeting %s, model %s", meeting_id, latest_model.id)
    return FEAResult(analysis=analysis, meta=meta)


# ---------------------------------------------------------------------------
# Technical Drawing (fal.ai gpt-image-2)
# ---------------------------------------------------------------------------


class TechnicalDrawingResult(BaseModel):
    drawing: TechnicalDrawing
    meta: dict


@router.post("/meetings/{meeting_id}/agent/drawing", tags=["agents"])
async def trigger_technical_drawing(meeting_id: UUID):
    """Generate a technical drawing using fal.ai gpt-image-2 based on the latest model."""
    import os
    import time

    import httpx

    _get_meeting_or_404(meeting_id)

    fal_key = os.getenv("FAL_KEY", "")
    if not fal_key:
        raise HTTPException(status_code=500, detail="FAL_KEY is not set. Add it to api/.env")

    current_models = store.models[meeting_id]
    if not current_models:
        raise HTTPException(status_code=400, detail="No model iterations yet — generate a 3D model first")

    latest_model = current_models[-1]
    current_blocks = store.blocks[meeting_id]

    try:
        # Build a description from plan blocks for the drawing prompt
        block_descriptions = []
        for b in current_blocks:
            try:
                c = b.content
                if c.block_type == "objective":
                    block_descriptions.append(f"Goal: {c.goal_statement}")
                elif c.block_type == "variable":
                    block_descriptions.append(f"{c.parameter_name}: {c.value} {c.unit}")
                elif c.block_type == "decision":
                    block_descriptions.append(f"Decision: {c.final_choice}")
            except Exception:
                pass

        design_desc = "; ".join(block_descriptions) if block_descriptions else "parametric 3D enclosure"

        prompt = (
            f"Technical engineering drawing with precise dimensions, orthographic projection views "
            f"(front, side, top), section views, and dimension annotations. "
            f"Professional drafting style on white background with thin black lines. "
            f"ISO standard technical drawing format. "
            f"The object: {design_desc}. "
            f"Show all critical dimensions in millimeters, include a title block, "
            f"scale reference, and standard engineering drawing annotations."
        )

        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
            resp = await client.post(
                "https://fal.run/openai/gpt-image-2",
                headers={"Authorization": f"Key {fal_key}", "Content-Type": "application/json"},
                json={"prompt": prompt},
            )
            resp.raise_for_status()
            result = resp.json()

        latency_ms = (time.perf_counter() - t0) * 1000

        # fal.ai gpt-image-2 response may vary in structure
        logger.info("fal.ai response keys: %s", list(result.keys()))
        images = (
            result.get("images")
            or result.get("output", {}).get("images", [])
            or result.get("data", [])
        )
        if not images:
            raise HTTPException(
                status_code=502,
                detail=f"fal.ai returned no images. Response: {str(result)[:500]}",
            )

        first = images[0]
        image_url = first.get("url", "") if isinstance(first, dict) else str(first)

        drawing = TechnicalDrawing(
            model_iteration_id=latest_model.id,
            image_url=image_url,
            prompt_used=prompt,
        )

        meta = {
            "provider": "fal.ai / gpt-image-2",
            "latency_ms": round(latency_ms, 1),
        }

        logger.info("Technical drawing generated for meeting %s, model %s", meeting_id, latest_model.id)
        return {"drawing": drawing.model_dump(mode="json"), "meta": meta}

    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        logger.error("fal.ai HTTP error: %s %s", e.response.status_code, e.response.text[:500])
        raise HTTPException(status_code=502, detail=f"fal.ai error: {e.response.status_code} {e.response.text[:300]}")
    except Exception as e:
        logger.error("Drawing endpoint unhandled error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Drawing generation failed: {e}")
