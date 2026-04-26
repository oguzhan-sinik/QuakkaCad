"""Thin wrapper around the MuBit SDK for OpenSCAD generation memory.

All functions are no-ops when MUBIT_API_KEY is not set, so the rest of the
codebase never needs to check for its presence.

The MuBit SDK is synchronous, so all calls are run in a thread pool to avoid
blocking the async event loop.  A short timeout prevents cold-start hangs.

SDK reference: https://docs.mubit.ai/sdk/sdk-methods
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_client: Any = None
_disabled = False

# Max seconds to wait for any single MuBit call (prevents first-call hang)
_TIMEOUT = 5

_AGENT_TEMPLATE = "template-classifier"

# One stable run_id for the shared template-library seed data.
# Using a fixed ID means re-seeding at startup is idempotent (MuBit deduplicates
# by content hash within a run, so repeated seeds don't bloat memory).
_TEMPLATE_LIBRARY_RUN_ID = "quakkacad:template-library:v1"


def _get_client() -> Any:
    """Lazily initialise the MuBit client.  Returns None if unavailable."""
    global _client, _disabled
    if _disabled:
        return None
    if _client is not None:
        return _client

    api_key = os.getenv("MUBIT_API_KEY", "")
    if not api_key:
        logger.info("MUBIT_API_KEY not set — MuBit integration disabled")
        _disabled = True
        return None

    try:
        from mubit import Client

        _client = Client()
        logger.info("MuBit client initialised")
        return _client
    except Exception as e:
        logger.warning("Failed to initialise MuBit client: %s", e)
        _disabled = True
        return None


async def _run_sync(fn, *args, **kwargs) -> Any:
    """Run a sync MuBit SDK call in a thread with timeout."""
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, lambda: fn(*args, **kwargs)),
            timeout=_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("MuBit call %s timed out after %ss", fn.__name__, _TIMEOUT)
        return None
    except Exception as e:
        logger.warning("MuBit call %s failed: %s", fn.__name__, e)
        return None


# ---------------------------------------------------------------------------
# General helpers (used by generate / planner / openscad-meeting agents)
# ---------------------------------------------------------------------------
# Template library helpers
# ---------------------------------------------------------------------------


def _build_template_seed_items() -> list[dict]:
    """Return a list of (content, metadata) dicts for each template.

    Each item describes the template's purpose, parameter schema, engineering
    constraints, and a short SCAD usage example. These are seeded once into
    MuBit so the template classifier agent can retrieve them as context.
    """
    items = [
        {
            "content": (
                "Template: finned_rocket_body\n"
                "Purpose: hollow cylindrical motor tube with trapezoidal fins and optional centering rings\n"
                "Parameters:\n"
                "  tube_outer_d (mm, 10-500): outer diameter of tube\n"
                "  tube_wall (mm, 0.5-20): tube wall thickness\n"
                "  tube_length (mm, 20-2000): axial length of tube\n"
                "  ring_count (0-4): number of centering rings\n"
                "  ring_width (mm, default 10): axial width of each ring\n"
                "  ring_radial_thickness (mm, default 4): radial thickness of ring material\n"
                "  ring_spacing (mm, optional): gap between rings; auto-computed if None\n"
                "  fin_count (0-8): number of fins\n"
                "  fin_root_chord (mm, default 80): fin root length along tube\n"
                "  fin_tip_chord (mm, default 30): fin tip length\n"
                "  fin_height (mm, default 60): fin span from tube surface\n"
                "  fin_sweep (mm, default 30): leading-edge sweep distance\n"
                "  fin_thickness (mm, default 2): fin thickness\n"
                "  fins_through_rings (bool, default True): cut slots in rings for fins\n"
                "Constraint: fin_root_chord <= tube_length\n"
                "Constraint: if ring_count>=2 and ring_spacing set, ring_spacing + ring_count*ring_width <= tube_length\n"
                "Typical use: model rocket bodies, high-power rockets, fin cans\n"
                "Keywords: rocket, fin, tube, motor mount, centering ring, fin can"
            ),
            "metadata": {"assembly_type": "finned_rocket_body", "kind": "template_spec"},
        },
        {
            "content": (
                "Template: gear_train\n"
                "Purpose: 2-6 meshing spur gears with correct center-distance spacing along X axis\n"
                "Parameters:\n"
                "  gear_count (2-6): number of gears in the train\n"
                "  teeth (list of ints, 8-80 each): tooth count per gear; length must equal gear_count\n"
                "  module_val (mm, 0.5-10): gear module — pitch diameter = module * teeth\n"
                "  thickness (mm, 1-50): gear face width\n"
                "  bore_d (mm, default 5): center bore diameter\n"
                "Center distance between adjacent gears: (teeth[i] + teeth[i+1]) * module_val / 2\n"
                "Meshing: odd-indexed gears rotate by half tooth pitch to interleave teeth\n"
                "Typical use: reduction drives, clock mechanisms, power transmission\n"
                "Keywords: gear, spur gear, reduction, gear train, transmission, mesh, teeth"
            ),
            "metadata": {"assembly_type": "gear_train", "kind": "template_spec"},
        },
        {
            "content": (
                "Template: bushing_assembly\n"
                "Purpose: cylindrical bushing or sleeve bearing with optional flange\n"
                "Parameters:\n"
                "  bore_d (mm, 1-200): inner bore diameter; must be < outer_d\n"
                "  outer_d (mm, 2-300): outer diameter\n"
                "  length (mm, 5-500): axial length of bushing\n"
                "  flange (bool, default False): add a flange at one end\n"
                "  flange_outer_d (mm, optional): flange OD; defaults to outer_d * 1.5\n"
                "  flange_thickness (mm, optional): flange thickness; defaults to 3mm\n"
                "Constraint: bore_d < outer_d\n"
                "Constraint: if flange=True, flange_outer_d > outer_d\n"
                "Typical use: pillow blocks, plain bearings, shaft guides, press-fit sleeves\n"
                "Keywords: bushing, bearing, sleeve, bore, shaft, press fit, flange"
            ),
            "metadata": {"assembly_type": "bushing_assembly", "kind": "template_spec"},
        },
        {
            "content": (
                "Template: flanged_tube\n"
                "Purpose: hollow tube with bolt-pattern flange(s) for pipe connections and pressure vessels\n"
                "Parameters:\n"
                "  tube_outer_d (mm, 5-500): tube outer diameter; must be < tube_inner_d by wall\n"
                "  tube_inner_d (mm, 1-500): tube inner diameter; must be < tube_outer_d\n"
                "  tube_length (mm, 10-2000): tube axial length\n"
                "  flange_outer_d (mm, 5-600): flange disc outer diameter; must be >= tube_outer_d\n"
                "  flange_thickness (mm, 1-50): flange disc thickness\n"
                "  bolt_count (3-24): number of bolt holes on bolt circle\n"
                "  bolt_circle_d (mm): bolt-hole circle diameter; must be > tube_outer_d and < flange_outer_d\n"
                "  bolt_hole_d (mm, default 5): bolt hole diameter\n"
                "  flange_both_ends (bool, default False): add flanges at both ends\n"
                "Constraint: tube_inner_d < tube_outer_d\n"
                "Constraint: flange_outer_d >= tube_outer_d\n"
                "Constraint: tube_outer_d < bolt_circle_d < flange_outer_d\n"
                "Typical use: pipe flanges, pressure vessels, exhaust flanges, manifolds\n"
                "Keywords: flange, pipe, tube, bolt pattern, pressure vessel, manifold, coupling"
            ),
            "metadata": {"assembly_type": "flanged_tube", "kind": "template_spec"},
        },
    ]
    return items


async def seed_template_library() -> None:
    """Seed MuBit with canonical template knowledge.

    Called once at startup. Uses a fixed run_id so re-seeding is idempotent —
    MuBit deduplicates content within a run. Safe to call on every startup.
    """
    client = _get_client()
    if client is None:
        return

    items = _build_template_seed_items()
    logger.info("Seeding %d templates into MuBit template library…", len(items))

    for item in items:
        try:
            await _run_sync(
                client.remember,
                session_id=_TEMPLATE_LIBRARY_RUN_ID,
                agent_id=_AGENT_TEMPLATE,
                content=item["content"],
                intent="fact",
                metadata=item["metadata"],
            )
        except Exception as e:
            logger.warning("MuBit template seed failed for %s: %s", item["metadata"].get("assembly_type"), e)

    logger.info("MuBit template library seeded")


async def get_template_context(user_prompt: str) -> str:
    """Retrieve template library context relevant to a user prompt via recall().

    Uses recall() (semantic search + synthesis) rather than get_context(), which
    returns an empty context_block in practice. Evidence content is joined into
    a plain-text block for injection into the LLM prompt.

    Returns an empty string if MuBit is unavailable (graceful degradation).
    """
    client = _get_client()
    if client is None:
        return ""

    try:
        result = await _run_sync(
            client.recall,
            session_id=_TEMPLATE_LIBRARY_RUN_ID,
            query=user_prompt,
        )
        if not result:
            logger.debug("MuBit template context empty")
            return ""

        parts = []

        # Synthesised answer from MuBit (short summary)
        final_answer = result.get("final_answer", "").strip()
        if final_answer:
            parts.append(f"Summary: {final_answer}")

        # Full content of each evidence item (facts, lessons, traces)
        for ev in result.get("evidence") or []:
            content = (ev.get("content") or "").strip()
            entry_type = ev.get("entry_type", "")
            if content and entry_type in ("fact", "lesson", "trace"):
                parts.append(content)

        text = "\n\n".join(parts)
        if text:
            logger.info("MuBit template context retrieved (%d chars, %d evidence items)",
                        len(text), len(result.get("evidence") or []))
        else:
            logger.debug("MuBit template context empty")
        return text
    except Exception as e:
        logger.warning("MuBit get_template_context failed: %s", e)
        return ""


async def remember_template_generation(
    prompt: str,
    assembly_type: str,
    scad_length: int,
    model_used: str,
) -> None:
    """Record a template classification + SCAD generation into the shared library session.

    Always writes to _TEMPLATE_LIBRARY_RUN_ID so traces accumulate in the same
    session that get_template_context() queries, enabling cross-request learning.
    """
    client = _get_client()
    if client is None:
        return

    try:
        content = (
            f"Template generation: {assembly_type}\n"
            f"Prompt: {prompt[:400]}\n"
            f"Model: {model_used}\n"
            f"SCAD output: {scad_length} chars"
        )
        await _run_sync(
            client.remember,
            session_id=_TEMPLATE_LIBRARY_RUN_ID,
            agent_id=_AGENT_TEMPLATE,
            content=content,
            intent="trace",
            metadata={
                "assembly_type": assembly_type,
                "model": model_used,
                "scad_length": scad_length,
            },
        )
        logger.info("MuBit memory saved: template generation assembly=%s scad_length=%d", assembly_type, scad_length)
    except Exception as e:
        logger.warning("MuBit template remember failed: %s", e)


async def record_template_outcome(
    assembly_type: str,
    success: bool,
    error_msg: str | None = None,
) -> None:
    """Record WASM compilation outcome into the shared library session.

    Always uses _TEMPLATE_LIBRARY_RUN_ID so reinforcement signals accumulate
    alongside the traces and seed facts that get_template_context() retrieves.
    MuBit's run→session→global promotion then surfaces lessons to future requests.
    """
    client = _get_client()
    if client is None:
        return

    try:
        reflection = await _run_sync(
            client.reflect,
            session_id=_TEMPLATE_LIBRARY_RUN_ID,
        )
        if not reflection:
            return

        lessons = reflection.get("lessons") or []
        logger.info("MuBit reflect: %d lesson(s) extracted for template library", len(lessons))
        lesson_id = next(
            (l.get("lesson_id") for l in lessons if l.get("lesson_id")),
            None,
        )
        if not lesson_id:
            logger.debug("MuBit reflect: no lesson_id found, skipping record_outcome")
            return

        outcome = "success" if success else "failure"
        signal = 1.0 if success else 0.0
        rationale = (
            f"Template {assembly_type}: WASM compilation succeeded"
            if success
            else f"Template {assembly_type}: WASM compilation failed: {error_msg or 'unknown'}"
        )

        await _run_sync(
            client.record_outcome,
            session_id=_TEMPLATE_LIBRARY_RUN_ID,
            agent_id=_AGENT_TEMPLATE,
            reference_id=lesson_id,
            outcome=outcome,
            signal=signal,
            rationale=rationale,
        )
        logger.info("MuBit outcome recorded: template assembly=%s outcome=%s", assembly_type, outcome)
    except Exception as e:
        logger.warning("MuBit record_template_outcome failed: %s", e)
