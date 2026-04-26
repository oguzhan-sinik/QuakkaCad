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
from mubit_client import record_template_outcome
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
    groq = "groq"
    cerebras = "cerebras"
    anthropic = "anthropic"


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
    provider: ProviderEnum = Query(default=ProviderEnum.anthropic),
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
            # Don't retry on system-level crashes (segfault)
            if "SIGSEGV" in (cq_result.stderr or ""):
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

    # Cache STL for FEA
    if stl_bytes:
        store.stl_cache[iteration.id] = stl_bytes

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
    """Fast template-based generation. Target: <8s e2e.

    The response includes a `session_id` in `meta` that the frontend should
    POST back to `/meetings/{meeting_id}/agent/template/outcome` once WASM
    compilation completes, to close the MuBit learning loop.
    """
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


class TemplateOutcomeRequest(BaseModel):
    assembly_type: str
    success: bool
    error: str | None = None
    session_id: str | None = None  # accepted but unused; learning goes to shared library session


@router.post("/meetings/{meeting_id}/agent/template/outcome", tags=["agents"])
async def report_template_outcome(meeting_id: UUID, body: TemplateOutcomeRequest):
    """Frontend reports whether WASM compilation of a template-generated model succeeded.

    Closes the MuBit feedback loop: reflect() extracts lessons from the shared
    template library session, then record_outcome() reinforces them so future
    get_template_context() calls surface better parameter guidance.
    """
    _get_meeting_or_404(meeting_id)
    asyncio.create_task(
        record_template_outcome(
            assembly_type=body.assembly_type,
            success=body.success,
            error_msg=body.error,
        )
    )
    return {"status": "ok"}


class FEAResult(BaseModel):
    analysis: FEAAnalysis
    meta: dict


class FEARequest(BaseModel):
    mesh_base64: str | None = None


@router.post("/meetings/{meeting_id}/agent/fea", response_model=FEAResult, tags=["agents"])
async def trigger_fea_analysis(meeting_id: UUID, body: FEARequest = FEARequest()):
    """Run real mesh-based FEA on the latest model, with LLM interpretation."""
    import base64
    import time

    _get_meeting_or_404(meeting_id)

    current_models = store.models[meeting_id]
    if not current_models:
        raise HTTPException(status_code=400, detail="No model iterations yet — generate a 3D model first")

    latest_model = current_models[-1]
    current_blocks = store.blocks[meeting_id]

    # 1. Get STL bytes — prefer frontend mesh, then cache, then recompile
    stl_bytes: bytes | None = None

    if body.mesh_base64:
        try:
            raw = base64.b64decode(body.mesh_base64)
            # Check if it's STL (binary STL starts with 80 byte header) or OFF (starts with "OFF")
            if raw[:3] == b"OFF" or raw[:4] == b"COFF":
                # Convert OFF to STL via meshio
                import tempfile
                import meshio
                from pathlib import Path
                with tempfile.TemporaryDirectory() as td:
                    off_path = Path(td) / "mesh.off"
                    stl_out = Path(td) / "mesh.stl"
                    off_path.write_bytes(raw)
                    mesh = meshio.read(str(off_path))
                    meshio.write(str(stl_out), mesh)
                    stl_bytes = stl_out.read_bytes()
                    logger.info("Converted frontend OFF to STL: %d bytes", len(stl_bytes))
            else:
                stl_bytes = raw
                logger.info("Using frontend STL mesh: %d bytes", len(stl_bytes))
        except Exception as e:
            logger.warning("Failed to decode frontend mesh: %s", e)

    if not stl_bytes:
        stl_bytes = store.stl_cache.get(latest_model.id)

    if not stl_bytes and latest_model.script_language == "cadquery":
        try:
            cq_result = await compile_cadquery(latest_model.script)
            if cq_result.success and cq_result.stl_bytes:
                stl_bytes = cq_result.stl_bytes
                store.stl_cache[latest_model.id] = stl_bytes
        except Exception as e:
            logger.warning("CadQuery recompile for FEA failed: %s", e)

    if not stl_bytes:
        # Fallback to LLM-only FEA
        try:
            analysis_dict, meta = await run_fea_analysis(
                script=latest_model.script, blocks=current_blocks,
            )
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
            return FEAResult(analysis=analysis, meta=meta)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"FEA error: {e}")

    # 2. Run real mesh-based FEA
    t0 = time.perf_counter()
    try:
        from fea_solver import run_mesh_fea
        solver_result = await run_mesh_fea(stl_bytes)
    except Exception as e:
        logger.error("Mesh FEA failed, falling back to LLM: %s", e, exc_info=True)
        # Fallback
        try:
            analysis_dict, meta = await run_fea_analysis(
                script=latest_model.script, blocks=current_blocks,
            )
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
            return FEAResult(analysis=analysis, meta=meta)
        except Exception as e2:
            raise HTTPException(status_code=502, detail=f"FEA error: {e2}")

    solve_ms = (time.perf_counter() - t0) * 1000

    # 3. LLM interpretation of real solver data
    try:
        stress_summary = (
            f"Max Von Mises: {solver_result.max_von_mises:.2f} MPa, "
            f"Min: {solver_result.min_von_mises:.2f} MPa, "
            f"Avg: {solver_result.avg_von_mises:.2f} MPa, "
            f"Safety Factor: {solver_result.safety_factor:.2f}"
        )
        top_points = "\n".join(
            f"  - ({p['x']:.1f}, {p['y']:.1f}, {p['z']:.1f}): {p['stress_mpa']:.2f} MPa"
            for p in solver_result.stress_points
        )
        interpretation_prompt = (
            f"FEA SOLVER RESULTS (real computation, not estimated):\n"
            f"{stress_summary}\n"
            f"Top stress concentration points:\n{top_points}\n\n"
            f"DESIGN:\n{latest_model.script[:500]}\n\n"
            f"Provide engineering interpretation: summary, recommendations, material notes."
        )
        analysis_dict, llm_meta = await run_fea_analysis(
            script=interpretation_prompt, blocks=current_blocks,
        )
    except Exception:
        # If LLM fails, use solver data directly
        analysis_dict = {
            "summary": f"FEA analysis complete. Peak stress {solver_result.max_von_mises:.1f} MPa with safety factor {solver_result.safety_factor:.1f}.",
            "stress_points": [f"({p['x']:.1f}, {p['y']:.1f}, {p['z']:.1f}): {p['stress_mpa']:.1f} MPa" for p in solver_result.stress_points],
            "recommendations": ["Review stress concentration areas for potential failure modes."],
            "material_notes": "Analysis assumes PLA (E=3500 MPa, yield=50 MPa).",
            "load_cases": ["Gravity (self-weight)"],
            "full_report": f"Peak Von Mises stress: {solver_result.max_von_mises:.2f} MPa\nSafety factor: {solver_result.safety_factor:.2f}",
        }

    analysis = FEAAnalysis(
        model_iteration_id=latest_model.id,
        summary=analysis_dict.get("summary", ""),
        stress_points=analysis_dict.get("stress_points", []),
        recommendations=analysis_dict.get("recommendations", []),
        material_notes=analysis_dict.get("material_notes", ""),
        safety_factor=solver_result.safety_factor,
        load_cases=analysis_dict.get("load_cases", []),
        full_report=analysis_dict.get("full_report", ""),
        stress_off=solver_result.stress_off,
        max_stress_mpa=solver_result.max_von_mises,
        min_stress_mpa=solver_result.min_von_mises,
    )

    meta = {
        "provider": "SfePy mesh FEA + LLM interpretation",
        "solve_ms": round(solve_ms, 1),
        "max_stress_mpa": solver_result.max_von_mises,
        "safety_factor": solver_result.safety_factor,
    }

    logger.info("Mesh FEA complete for meeting %s: max=%.1f MPa, SF=%.1f, solve=%.0fms",
                meeting_id, solver_result.max_von_mises, solver_result.safety_factor, solve_ms)
    return FEAResult(analysis=analysis, meta=meta)


# ---------------------------------------------------------------------------
# Technical Drawing (fal.ai gpt-image-2)
# ---------------------------------------------------------------------------


class TechnicalDrawingResult(BaseModel):
    drawing: TechnicalDrawing
    meta: dict


class DrawingRequest(BaseModel):
    reference_images: list[str] = []


@router.post("/meetings/{meeting_id}/agent/drawing", tags=["agents"])
async def trigger_technical_drawing(meeting_id: UUID, body: DrawingRequest = DrawingRequest()):
    """Generate a technical drawing using fal.ai with optional 3D view screenshots."""
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
        # Build a description from plan blocks
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

        # Extract dimensions from the OpenSCAD/CadQuery script
        import re
        dimensions = []
        for line in latest_model.script.split("\n"):
            # Match variable assignments like: width = 60; or tube_outer_d = 90
            m = re.match(r"^\s*(\w+)\s*=\s*([\d.]+)\s*;?\s*(?://\s*(.+))?", line)
            if m and not m.group(1).startswith("$"):
                name = m.group(1).replace("_", " ")
                val = m.group(2)
                comment = m.group(3) or ""
                dimensions.append(f"{name}: {val}mm" + (f" ({comment.strip()})" if comment.strip() else ""))
        dim_text = "; ".join(dimensions[:15]) if dimensions else ""

        if body.reference_images:
            n_imgs = len(body.reference_images)
            prompt = (
                f"Convert these {n_imgs} 3D CAD model screenshots (front elevation, top/plan view, "
                f"and isometric 3/4 perspective) into a professional ISO technical engineering drawing. "
                f"Create orthographic projection layout with front view, side view, and top view. "
                f"Add precise dimension lines with arrows and annotations in millimeters for ALL key features. "
                f"Use thin black lines on white background. Professional drafting style. "
                f"Include a title block in the bottom right corner. "
                f"The object: {design_desc}. "
            )
            if dim_text:
                prompt += f"Key dimensions to annotate: {dim_text}. "
        else:
            prompt = (
                f"Technical engineering drawing with precise dimensions, orthographic projection views "
                f"(front, side, top), section views, and dimension annotations. "
                f"Professional drafting style on white background with thin black lines. "
                f"ISO standard technical drawing format. "
                f"The object: {design_desc}. "
                f"Show all critical dimensions in millimeters, include a title block. "
            )
            if dim_text:
                prompt += f"Key dimensions: {dim_text}. "

        has_refs = len(body.reference_images) > 0
        t0 = time.perf_counter()

        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
            fal_headers = {"Authorization": f"Key {fal_key}", "Content-Type": "application/json"}

            if has_refs:
                # Upload screenshots to fal.ai storage to get real URLs
                import base64 as b64mod
                image_urls = []
                for idx, b64img in enumerate(body.reference_images[:3]):
                    try:
                        img_bytes = b64mod.b64decode(b64img)
                        up_resp = await client.post(
                            "https://fal.ai/api/storage/upload/url",
                            headers={"Authorization": f"Key {fal_key}", "Content-Type": "image/png"},
                            content=img_bytes,
                        )
                        if up_resp.status_code == 200:
                            up_data = up_resp.json()
                            url = up_data.get("file_url") or up_data.get("url") or up_data.get("access_url", "")
                            if url:
                                image_urls.append(url)
                                logger.info("Uploaded screenshot %d to fal: %s", idx, url[:80])
                            else:
                                logger.warning("Upload %d returned no URL: %s", idx, up_data)
                        else:
                            logger.warning("Upload %d failed: %d %s", idx, up_resp.status_code, up_resp.text[:200])
                    except Exception as e:
                        logger.warning("Upload %d error: %s", idx, e)

                if not image_urls:
                    logger.warning("All uploads failed, falling back to text-only generation")
                    has_refs = False

            if has_refs and image_urls:
                logger.info("Sending %d uploaded reference images to GPT Image 2 Edit", len(image_urls))
                # GPT Image 2 Edit (high-quality image-to-image)
                resp = await client.post(
                    "https://fal.run/openai/gpt-image-2/edit",
                    headers=fal_headers,
                    json={
                        "prompt": prompt,
                        "image_urls": image_urls,
                        "quality": "high",
                        "output_format": "png",
                        "num_images": 1,
                    },
                )
            else:
                # No reference images — Flux Schnell (text-to-image)
                resp = await client.post(
                    "https://fal.run/fal-ai/flux/schnell",
                    headers=fal_headers,
                    json={"prompt": prompt, "image_size": "landscape_16_9", "num_images": 1},
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
            "provider": f"fal.ai / {'GPT Image 2 Edit' if has_refs else 'Flux Schnell'}",
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
