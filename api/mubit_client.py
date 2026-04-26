"""Thin wrapper around the MuBit SDK for OpenSCAD generation memory.

All functions are no-ops when MUBIT_API_KEY is not set, so the rest of the
codebase never needs to check for its presence.

The MuBit SDK is synchronous, so all calls are run in a thread pool to avoid
blocking the async event loop.  A short timeout prevents cold-start hangs.

SDK reference: https://docs.mubit.ai/sdk/sdk-methods

Correct helper signatures (Python SDK >=0.6.0):
  client.remember(session_id, agent_id, content, intent, metadata)
  client.get_context(session_id, query, mode, max_token_budget)
  client.reflect(session_id)
  client.record_outcome(session_id, agent_id, reference_id, outcome, signal, rationale)
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

# Stable agent IDs used across all helpers
_AGENT_TEMPLATE = "template-classifier"
_AGENT_OPENSCAD = "openscad-generator"
_AGENT_PLANNER = "planner"
_AGENT_OPENSCAD_MEETING = "openscad-meeting"
_AGENT_OPENSCAD_REFINE = "openscad-refine"

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


async def get_generation_context(
    agent_id: str,
    session_id: str,
    max_tokens: int = 500,
) -> str:
    """Retrieve past lessons/context for this agent before an LLM call.

    Uses get_context() with a query tailored to the agent role so MuBit
    returns the most relevant lessons (parameter ranges, past errors, etc.).
    """
    client = _get_client()
    if client is None:
        return ""

    query_for_agent = {
        _AGENT_OPENSCAD: "OpenSCAD generation lessons: syntax errors avoided, parameter defaults, compilable patterns",
        _AGENT_PLANNER: "CAD planning lessons: block extraction, variable locking, transcript relevance",
        _AGENT_OPENSCAD_MEETING: "OpenSCAD meeting generation: enclosure geometry, plan block mapping",
        _AGENT_OPENSCAD_REFINE: "OpenSCAD refinement: quality improvements, extended thinking, compile fixes",
        _AGENT_TEMPLATE: "Template classifier lessons: assembly type selection, parameter ranges, unit conversion",
    }.get(agent_id, f"lessons for {agent_id} agent")

    try:
        context = await _run_sync(
            client.get_context,
            session_id=session_id,
            query=query_for_agent,
            mode="summary",
            max_token_budget=max_tokens,
        )
        if context is None:
            return ""

        if isinstance(context, dict):
            text = (
                context.get("context_block")
                or context.get("section_summaries")
                or context.get("context")
                or context.get("text")
                or ""
            )
            if isinstance(text, list):
                text = "\n".join(str(s) for s in text)
        else:
            text = str(context) if context else ""

        result = text.strip() if text and text.strip() else ""
        if result:
            logger.info("MuBit context retrieved for agent=%s (%d chars)", agent_id, len(result))
        else:
            logger.debug("MuBit context empty for agent=%s", agent_id)
        return result
    except Exception as e:
        logger.warning("MuBit get_context failed: %s", e)
        return ""


async def remember_generation(
    agent_id: str,
    session_id: str,
    prompt: str,
    code: str,
    model_used: str,
) -> None:
    """Store a generation interaction as a fact in MuBit memory."""
    client = _get_client()
    if client is None:
        return

    try:
        content = (
            f"Prompt: {prompt[:500]}\n"
            f"Model: {model_used}\n"
            f"Generated code ({len(code)} chars):\n{code[:1000]}"
        )
        await _run_sync(
            client.remember,
            session_id=session_id,
            agent_id=agent_id,
            content=content,
            intent="trace",
            metadata={"model": model_used, "code_length": len(code)},
        )
        logger.info("MuBit memory saved: agent=%s session=%s code_length=%d", agent_id, session_id, len(code))
    except Exception as e:
        logger.warning("MuBit remember failed: %s", e)


async def record_generation_outcome(
    session_id: str,
    success: bool,
    error_msg: str | None = None,
    agent_id: str = _AGENT_OPENSCAD_MEETING,
) -> None:
    """Reflect on the session and record the compilation outcome as reinforcement.

    MuBit's record_outcome() requires a lesson reference_id (from reflect()),
    so we call reflect() first to extract lessons, then reinforce the most
    recent lesson with the outcome signal.
    """
    client = _get_client()
    if client is None:
        return

    try:
        # Reflect to extract lessons from this session
        reflection = await _run_sync(client.reflect, session_id=session_id)
        if not reflection:
            return

        lessons = reflection.get("lessons") or []
        logger.info("MuBit reflect: %d lesson(s) extracted for session=%s", len(lessons), session_id)
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
            "OpenSCAD/CadQuery compilation succeeded"
            if success
            else f"Compilation failed: {error_msg or 'unknown error'}"
        )

        await _run_sync(
            client.record_outcome,
            session_id=session_id,
            agent_id=agent_id,
            reference_id=lesson_id,
            outcome=outcome,
            signal=signal,
            rationale=rationale,
        )
        logger.info("MuBit outcome recorded: agent=%s session=%s outcome=%s", agent_id, session_id, outcome)
    except Exception as e:
        logger.warning("MuBit record_outcome failed: %s", e)


async def reflect_on_session(session_id: str) -> None:
    """Extract lessons from this generation session.

    Note: record_generation_outcome() already calls reflect() internally.
    Only call this standalone when you want to trigger reflection without
    recording a reinforcement outcome (e.g. for the planner agent).
    """
    client = _get_client()
    if client is None:
        return

    try:
        await _run_sync(client.reflect, session_id=session_id)
    except Exception as e:
        logger.warning("MuBit reflect failed: %s", e)


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


_AGENT_DEFINITIONS = [
    {
        "agent_id": _AGENT_TEMPLATE,
        "role": "template classifier",
        "description": "Classifies natural-language CAD prompts into typed assembly specs with validated parameters",
        "system_prompt_content": (
            "You are a CAD template classifier. Given a user request, select the most appropriate "
            "assembly template and extract precise parameter values. Output valid JSON matching the "
            "AssemblySpec schema. Respect all engineering constraints (bore < outer diameter, "
            "fin chord ≤ tube length, bolt circle between tube OD and flange OD, etc.)."
        ),
    },
    {
        "agent_id": _AGENT_OPENSCAD,
        "role": "OpenSCAD code generator",
        "description": "Generates compilable OpenSCAD source from CAD planning blocks and meeting transcripts",
        "system_prompt_content": (
            "You are an OpenSCAD code generator. Produce syntactically correct, compilable OpenSCAD "
            "source. Use parametric variables, avoid hardcoded magic numbers, and structure code with "
            "named modules. Never emit CadQuery or Python — only OpenSCAD."
        ),
    },
    {
        "agent_id": _AGENT_PLANNER,
        "role": "CAD planner",
        "description": "Extracts structured CAD planning blocks from meeting transcripts",
        "system_prompt_content": (
            "You are a CAD planning agent. Analyse meeting transcripts and extract structured "
            "design intent: components, dimensions, materials, and constraints. Output clean "
            "planning blocks that downstream code-generation agents can consume directly."
        ),
    },
    {
        "agent_id": _AGENT_OPENSCAD_MEETING,
        "role": "OpenSCAD meeting agent",
        "description": "Generates OpenSCAD models from meeting-derived CAD plan blocks",
        "system_prompt_content": (
            "You are an OpenSCAD generation agent working from structured CAD plan blocks. "
            "Map each plan block to geometry, honour all stated dimensions and constraints, "
            "and produce a single compilable OpenSCAD file."
        ),
    },
    {
        "agent_id": _AGENT_OPENSCAD_REFINE,
        "role": "OpenSCAD refinement agent",
        "description": "Iteratively fixes and improves OpenSCAD source until it compiles cleanly",
        "system_prompt_content": (
            "You are an OpenSCAD refinement agent. Given OpenSCAD source and compiler error output, "
            "diagnose and fix all syntax and semantic errors. Preserve the original design intent "
            "while ensuring the output compiles without warnings."
        ),
    },
]


async def ensure_agents_registered() -> None:
    """Create MuBit agent definitions for all QuakkaCad agents.

    Safe to call on every startup — exceptions from duplicate creation are
    caught and logged so a pre-existing agent never blocks startup.
    """
    client = _get_client()
    if client is None:
        return

    project_id = os.getenv("MUBIT_PROJECT_ID", "")
    if not project_id:
        logger.warning("MUBIT_PROJECT_ID not set — skipping agent registration")
        return

    for defn in _AGENT_DEFINITIONS:
        try:
            await _run_sync(
                client.create_agent_definition,
                project_id=project_id,
                agent_id=defn["agent_id"],
                role=defn["role"],
                description=defn["description"],
                system_prompt_content=defn["system_prompt_content"],
            )
            logger.info("MuBit agent registered: %s", defn["agent_id"])
        except Exception as e:
            # Already exists or transient error — either way non-fatal
            logger.debug("MuBit agent registration skipped for %s: %s", defn["agent_id"], e)


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


async def get_template_context(user_prompt: str, max_tokens: int = 600) -> str:
    """Retrieve template library context relevant to a user prompt.

    Used by the template classifier agent before the LLM call to surface:
    - which template types are available and their parameter schemas
    - past lessons about parameter selection and compilation outcomes
    - engineering constraints that commonly cause failures

    Returns an empty string if MuBit is unavailable (graceful degradation).
    """
    client = _get_client()
    if client is None:
        return ""

    try:
        context = await _run_sync(
            client.get_context,
            session_id=_TEMPLATE_LIBRARY_RUN_ID,
            query=user_prompt,
            mode="summary",
            max_token_budget=max_tokens,
        )
        if context is None:
            return ""

        if isinstance(context, dict):
            text = (
                context.get("context_block")
                or context.get("section_summaries")
                or context.get("context")
                or context.get("text")
                or ""
            )
            if isinstance(text, list):
                text = "\n".join(str(s) for s in text)
        else:
            text = str(context) if context else ""

        result = text.strip() if text and text.strip() else ""
        if result:
            logger.info("MuBit template context retrieved (%d chars)", len(result))
        else:
            logger.debug("MuBit template context empty")
        return result
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
