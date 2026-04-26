from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Literal, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.models.anthropic import AnthropicModelSettings

from mubit_client import get_generation_context, record_generation_outcome, reflect_on_session, remember_generation
from schemas import (
    AnyBlockContent,
    DecisionContent,
    MissingInfoContent,
    ModelIterationCreate,
    ObjectiveContent,
    PlanBlock,
    PlanBlockCreate,
    ScriptEdit,
    TranscriptEntry,
    VariableContent,
)

load_dotenv(Path(__file__).parent / ".env")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Transcript relevance classification
# ---------------------------------------------------------------------------

_DESIGN_KEYWORDS: set[str] = {
    "mm", "cm", "inch", "inches", "meter", "meters",
    "thick", "thickness", "thin", "wide", "width", "height", "tall",
    "long", "length", "depth", "diameter", "radius", "size",
    "enclosure", "bracket", "mount", "mounting", "holder",
    "hole", "holes", "screw", "screws", "bolt", "nut", "standoff",
    "wall", "chamfer", "fillet", "rounded", "bevel",
    "edge", "corner", "slot", "groove", "cutout", "opening", "notch",
    "lid", "base", "top", "bottom", "side", "panel",
    "pla", "abs", "petg", "aluminum", "steel", "acrylic", "wood", "nylon",
    "cylinder", "cube", "sphere", "box", "cone", "torus", "tube",
    "dimension", "tolerance", "clearance", "offset", "extrude",
    "3d", "cad", "model", "print", "printer", "printed", "design",
    "pcb", "board", "battery", "sensor", "led", "wire", "motor",
    "connector", "usb", "port", "vent", "ventilation", "fan",
    "snap", "clip", "hinge", "latch", "tab", "rib", "gusset",
    "openscad", "stl", "mesh", "geometry", "parametric",
}

_IRRELEVANT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\b(hi|hello|hey|bye|goodbye|see you|take care)\b",
        r"\b(lunch|coffee|bathroom|break time|let'?s take a break)\b",
        r"\b(how are you|how'?s it going|what'?s up|good morning|good afternoon|good evening)\b",
        r"\b(schedule|calendar|meeting room|zoom|teams)\b",
        r"\b(weekend|vacation|holiday|birthday|party)\b",
    ]
]


def classify_relevance_heuristic(text: str) -> bool | None:
    """Classify transcript line relevance using keyword heuristics.

    Returns True (design-relevant), False (off-topic), or None (ambiguous).
    """
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    design_overlap = words & _DESIGN_KEYWORDS

    # Strong design signal
    if len(design_overlap) >= 2:
        return True
    # Short utterance with a design word is likely relevant
    if len(design_overlap) >= 1 and len(words) <= 8:
        return True

    # Check irrelevant patterns only if no design words at all
    if not design_overlap:
        for pattern in _IRRELEVANT_PATTERNS:
            if pattern.search(text):
                return False

    return None  # ambiguous — needs LLM


RELEVANCE_CLASSIFIER_PROMPT = """\
You classify transcript lines from a CAD design meeting.
For each line, decide: is it relevant to the 3D physical design being discussed?

Relevant = dimensions, materials, geometry, components, design decisions, assembly, manufacturing.
Irrelevant = social chat, scheduling, off-topic, greetings, jokes, food.

Return ONLY a JSON array of booleans, one per input line, same order. Example: [true, false, true]\
"""

_relevance_agents: dict[str, Any] = {}


def _get_relevance_agent(provider: str) -> Agent:
    if provider not in _relevance_agents:
        _relevance_agents[provider] = Agent(
            _make_model(provider),
            system_prompt=RELEVANCE_CLASSIFIER_PROMPT,
            output_type=str,
            retries=1,
        )
    return _relevance_agents[provider]


async def classify_relevance_batch(
    entries: list[TranscriptEntry],
    provider: str = "cerebras",
) -> list[bool]:
    """Classify a batch of transcript entries using the LLM. Returns list of booleans."""
    if not entries:
        return []

    _require_key(provider)
    agent = _get_relevance_agent(provider)

    numbered = "\n".join(f"{i+1}. {e.text}" for i, e in enumerate(entries))
    prompt = f"Classify these {len(entries)} lines:\n{numbered}"

    try:
        result = await asyncio.wait_for(
            agent.run(prompt, model_settings={"temperature": 0.0, "max_tokens": 256}),
            timeout=10,
        )
        raw = _strip_markdown_fences(_strip_think_blocks(result.output)).strip()
        parsed = json.loads(raw)
        if isinstance(parsed, list) and len(parsed) == len(entries):
            return [bool(x) for x in parsed]
        logger.warning("Relevance classifier returned wrong length: %d vs %d", len(parsed), len(entries))
    except Exception as e:
        logger.warning("Relevance batch classification failed: %s", e)

    # Fallback: assume all relevant (safe default)
    return [True] * len(entries)


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

GENERATE_SYSTEM_PROMPT = (Path(__file__).parent / "prompt.md").read_text()

PLANNER_SYSTEM_PROMPT = """\
You are the MuBit Planner Agent. Parse hackathon meeting transcripts and extract \
structured plan blocks for a CAD design project.

Output a JSON object with exactly two top-level keys:
  "blocks_to_create": array of block objects (omit "id")
  "blocks_to_update": array of block objects (must include "id" UUID of the existing block)

Each block object must have:
  "block_type": one of "objective", "variable", "decision", "missing_info"
  "reasoning": string ≥ 10 chars citing specific transcript evidence

Type-specific fields (include only the relevant ones):
  objective:    "goal_statement" (string), "success_criteria" (array of strings)
  variable:     "parameter_name" (string), "value" (number), "unit" (string), "is_locked" (bool)
  decision:     "final_choice" (string), "rejected_alternatives" (array of strings)
  missing_info: "blocking_parameter" (string), "impact" (string)

Block types and when to use them:
  objective    - physical build goal; populate success_criteria as a strict list
  variable     - a numeric parameter (dimensions, voltages, weights); set is_locked=true
                 ONLY when the team explicitly agreed on that exact value; use is_locked=false
                 with a sensible default for any parameter that is estimated or typical for the object
  decision     - a design choice; list rejected_alternatives explicitly mentioned
  missing_info - ONLY use when a value is truly unresolvable (e.g. a custom PCB board whose
                 dimensions have never been mentioned and cannot be estimated); do NOT use for
                 things that have well-known typical dimensions or that the CAD agent can draft
                 with a reasonable default

Rules:
- reasoning must be ≥ 10 chars and cite specific transcript evidence
- Prefer an unlocked variable with a sensible default over a missing_info block; reserve
  missing_info for parameters that are both unknown AND cannot be estimated from context\
"""

OPENSCAD_EDIT_SYSTEM_PROMPT = """\
You are the MuBit OpenSCAD Edit Agent. Given an existing valid OpenSCAD script and \
a set of changed plan blocks, return a minimal list of search-and-replace edits.

Rules:
- Prefer updating variable declarations at the top (e.g. board_length = 102; → board_length = 110;)
- Only touch geometry when a decision or objective block explicitly changed the form factor
- Each search string must match exactly one location in the script
- Do not rewrite the whole file — only the minimum edits to reflect the changed blocks
- Preserve existing color() calls unless a decision block explicitly changed part colours
- reasoning must cite which blocks drove each edit
- applied_lessons: list specific CAD heuristics or past compilation errors avoided\
"""

OPENSCAD_MEETING_SYSTEM_PROMPT = """\
You are the MuBit OpenSCAD Agent. Generate valid, compilable OpenSCAD code for \
a 3D enclosure based on the project's plan blocks.

Output ONLY raw OpenSCAD — no markdown fences, no prose.

Rules:
- Declare all parametric dimensions as variables at the top of the file
- Pull exact values from LOCKED variable blocks; use commented defaults for unlocked ones
- The objective block defines the physical form (enclosure, bracket, housing, etc.)
- decision blocks inform geometry choices (mounting holes, wall thickness, etc.)
- missing_info blocks: substitute a sensible default and add a // TODO comment
- Use color() to visually distinguish parts (e.g. body vs lid vs hardware)
- reasoning must explain your geometric decisions
- applied_lessons: list specific CAD heuristics or past compilation errors avoided\
"""

OPENSCAD_FIX_SYSTEM_PROMPT = """\
You are the MuBit OpenSCAD Fix Agent. Given an OpenSCAD script and its compiler \
stderr output, return a corrected version of the complete script.

Output ONLY raw OpenSCAD — no markdown fences, no prose, no explanation.

Rules:
- Fix exactly what the ERROR: lines describe — do not change anything else
- Preserve all variable names, comments, color() calls, and structure outside the error sites
- If an error is ambiguous, choose the minimal fix that makes the script valid\
"""

OPENSCAD_REFINE_SYSTEM_PROMPT = """\
You are a senior OpenSCAD engineer with deep knowledge of parametric 3D design.
You are given design plan blocks and optionally a previous draft script.

Your task: produce a high-quality, fully compilable, clean parametric OpenSCAD model.

Rules:
- Ignore plan blocks unrelated to physical geometry (workflow notes, team decisions about
  non-geometric matters, abstract project goals)
- Focus on: objective blocks (form factor), variable blocks (dimensions), decision blocks
  (geometry choices such as mounting holes, chamfers, wall thickness)
- Declare ALL numeric parameters as named variables at the top of the file
- Use union(), difference(), intersection() correctly — no syntax errors
- Add // TODO comments for any missing_info blocks (substitute sensible defaults)
- Use color() to visually distinguish major parts (e.g. body, lid, inserts)
- reasoning must explain every significant geometric decision made
- applied_lessons: note any CAD heuristics applied (e.g. tolerances, printability)\
"""

FEA_ANALYSIS_SYSTEM_PROMPT = """\
You are a senior mechanical / structural engineer performing a Finite Element Analysis \
(FEA) review of a 3D CAD model described in OpenSCAD code.

Given the OpenSCAD script and its design plan blocks, produce:
1. A thorough engineering analysis report
2. A MODIFIED OpenSCAD script that visualises stress as a colour heat-map directly on the 3D geometry

COLOUR HEAT-MAP RULES for the visualisation script:
- Use color() calls on EVERY geometric primitive / module call to show stress levels
- color([1,0,0]) = RED = high stress (stress concentrators, thin walls near holes, sharp corners)
- color([1,0.65,0]) = ORANGE = medium-high stress
- color([1,1,0]) = YELLOW = medium stress
- color([0.5,1,0]) = LOW-MEDIUM stress
- color([0,0.8,0]) = GREEN = low stress (bulk material, well-supported areas)
- Break the original geometry into sub-regions where needed to apply different colours
- The script MUST be valid, compilable OpenSCAD — no markdown fences, no prose in the script
- Preserve all original dimensions and geometry — only add/change color() calls
- Add a comment legend at the top: // FEA STRESS HEAT MAP — Red=High, Orange=Med-High, Yellow=Med, Green=Low

Your analysis MUST cover:
1. Stress Analysis: stress concentration points, Von Mises stress peaks
2. Load Cases: realistic scenarios (gravity, handling, stacking, thermal, insertion forces)
3. Material Considerations: yield strength, layer adhesion, print orientation
4. Safety Factor: estimated numeric factor
5. Failure Modes: buckling, fatigue, creep, delamination, brittle fracture
6. Design Recommendations: actionable fixes (fillets, thickness, ribs, orientation)

Output a JSON object with these exact keys:
  "summary": string (2-3 sentence overview)
  "stress_points": array of strings (location + criticality)
  "recommendations": array of strings (actionable fixes)
  "material_notes": string
  "safety_factor": number or null
  "load_cases": array of strings
  "full_report": string (detailed markdown, 500-1000 words)
  "stress_script": string (the COMPLETE modified OpenSCAD script with colour heat-map)
"""

_fea_agents: dict[str, Any] = {}


def _get_fea_agent(provider: str) -> Agent:
    if provider not in _fea_agents:
        _fea_agents[provider] = Agent(
            _make_model(provider),
            system_prompt=FEA_ANALYSIS_SYSTEM_PROMPT,
            output_type=str,
            retries=1,
        )
    return _fea_agents[provider]


# ---------------------------------------------------------------------------
# CadQuery system prompts
# ---------------------------------------------------------------------------

CADQUERY_MEETING_SYSTEM_PROMPT = """\
You are the MuBit CadQuery Agent. Generate valid, executable Python code using \
CadQuery to create a 3D model based on the project's plan blocks.

Output ONLY raw Python code — no markdown fences, no prose.

STRICT RULES:
- The ONLY import allowed is: import cadquery as cq
- Do NOT import numpy, sys, os, math or any other module. Use Python builtins for math.
- Do NOT add install checks, try/except around imports, or print statements
- Do NOT add if __name__ == "__main__" blocks
- Declare all parametric dimensions as variables at the top of the file
- Pull exact values from LOCKED variable blocks; use commented defaults for unlocked ones
- Assign the final Workplane object to a variable called `result`
- Use CadQuery operations: .box(), .cylinder(), .sphere(), .hole(), .fillet(), .chamfer(), .shell()
- Use .union(), .cut(), .intersect() for Boolean operations
- Use .translate(), .rotate() for positioning
- For circles/arcs use math: 3.14159 instead of math.pi
- For arrays of parts, use Python list comprehension + .union() in a loop

Example of CORRECT CadQuery code:
```
import cadquery as cq

# Parameters
length = 100
width = 60
height = 40
wall = 3
fillet_r = 2

# Main body - hollow box
body = (cq.Workplane("XY")
    .box(length, width, height)
    .edges("|Z").fillet(fillet_r)
    .shell(-wall))

# Mounting holes
body = (body.faces(">Z").workplane()
    .rect(length - 10, width - 10, forConstruction=True)
    .vertices()
    .hole(3.2))

result = body
```

- reasoning must explain your geometric decisions
- applied_lessons: list specific CAD heuristics or past compilation errors avoided
"""

CADQUERY_EDIT_SYSTEM_PROMPT = """\
You are the MuBit CadQuery Edit Agent. Given an existing valid CadQuery Python script \
and a set of changed plan blocks, return a minimal list of search-and-replace edits.

Rules:
- Prefer updating variable declarations at the top (e.g. board_length = 102 → board_length = 110)
- Only touch geometry when a decision or objective block explicitly changed the form factor
- Each search string must match exactly one location in the script
- Do not rewrite the whole file — only the minimum edits to reflect the changed blocks
- reasoning must cite which blocks drove each edit
- applied_lessons: list specific CAD heuristics or past compilation errors avoided
"""

CADQUERY_FIX_SYSTEM_PROMPT = """\
You are the MuBit CadQuery Fix Agent. Given a CadQuery Python script and its error \
output (traceback), return a corrected version of the complete script.

Output ONLY raw Python code — no markdown fences, no prose, no explanation.

Rules:
- Fix exactly what the error describes — do not change anything else
- The ONLY import allowed is: import cadquery as cq
- Do NOT import numpy, sys, os, math or any other module
- Do NOT add install checks or try/except around imports
- Preserve all variable names, comments, and structure outside the error sites
- The final result MUST be assigned to a variable called `result`
- Common CadQuery pitfalls to watch for:
  - .val() vs .vals() confusion
  - Workplane chaining errors
  - Selector string syntax (">Z", "<X", etc.)
  - fillet/chamfer on edges that don't exist
  - translate() takes a tuple, not separate args: .translate((x, y, z))
"""

CADQUERY_REFINE_SYSTEM_PROMPT = """\
You are a senior mechanical CAD engineer with deep knowledge of parametric 3D design \
using CadQuery. You are given design plan blocks and optionally a previous draft script.

Your task: produce a high-quality, fully executable, clean parametric CadQuery model.

Rules:
- Start with: import cadquery as cq
- Ignore plan blocks unrelated to physical geometry
- Focus on: objective blocks (form factor), variable blocks (dimensions), decision blocks \
  (geometry choices such as mounting holes, chamfers, wall thickness)
- Declare ALL numeric parameters as named variables at the top of the file
- Use proper CadQuery operations and Boolean ops
- Add # TODO comments for any missing_info blocks (substitute sensible defaults)
- Assign the final result to a variable called `result`
- reasoning must explain every significant geometric decision made
- applied_lessons: note any CAD heuristics applied
"""

_cadquery_meeting_agents: dict[str, Any] = {}
_cadquery_edit_agents: dict[str, Any] = {}
_cadquery_fix_agents: dict[str, Any] = {}
_cadquery_refine_agents: dict[str, Any] = {}


def _get_cadquery_meeting_agent(provider: str) -> Agent:
    if provider not in _cadquery_meeting_agents:
        _cadquery_meeting_agents[provider] = Agent(
            _make_model(provider),
            system_prompt=CADQUERY_MEETING_SYSTEM_PROMPT,
            output_type=ModelIterationCreate,
            retries=1,
        )
    return _cadquery_meeting_agents[provider]


def _get_cadquery_fix_agent(provider: str) -> Agent:
    if provider not in _cadquery_fix_agents:
        _cadquery_fix_agents[provider] = Agent(
            _make_model(provider),
            system_prompt=CADQUERY_FIX_SYSTEM_PROMPT,
            output_type=str,
            retries=1,
        )
    return _cadquery_fix_agents[provider]


_OPENSCAD_NOISE = re.compile(
    r"^(Could not initialize|WARNING: could not initialize|Application path is|"
    r"Converted \d+ warning|QtCore|QStandardPaths|QFactoryLoader|ALSA)",
    re.IGNORECASE,
)


def _filter_openscad_stderr(stderr: str | None) -> str | None:
    if not stderr:
        return stderr
    lines = [l for l in stderr.splitlines() if not _OPENSCAD_NOISE.match(l)]
    return "\n".join(lines).strip() or None


# ---------------------------------------------------------------------------
# Provider config
# ---------------------------------------------------------------------------

PROVIDER_CONFIG: dict[str, dict] = {
    "groq": {
        "model": "gateway/groq:llama-3.3-70b-versatile",
        "model_name": "llama-3.3-70b-versatile",
        "label": "Pydantic Gateway / Groq (Llama 3.3 70B)",
        "key_env": "PYDANTIC_AI_GATEWAY_API_KEY",
    },
    "cerebras": {
        "direct_base_url": "https://api.cerebras.ai/v1",
        "model_name": "qwen-3-235b-a22b-instruct-2507",
        "label": "Cerebras (Qwen3 235B Instruct)",
        "key_env": "CEREBRAS_API_KEY",
    },
    "anthropic": {
        "model": "gateway/anthropic:claude-opus-4-7",
        "model_name": "claude-opus-4-7",
        "label": "Pydantic Gateway / Anthropic (Claude Opus 4.7)",
        "key_env": "PYDANTIC_AI_GATEWAY_API_KEY",
    },
}

# ---------------------------------------------------------------------------
# Agent output schemas
# ---------------------------------------------------------------------------


class PlannerOutput(BaseModel):
    blocks_to_create: list[PlanBlockCreate] = Field(default_factory=list)
    blocks_to_update: list[PlanBlock] = Field(
        default_factory=list,
        description="Full PlanBlock objects (with correct id) to overwrite existing blocks",
    )


class OpenSCADEditOutput(BaseModel):
    edits: list[ScriptEdit]
    reasoning: str
    applied_lessons: list[str] = Field(default_factory=list)


# LLM-facing flat schemas for the planner (no discriminated union)
class LLMBlockCreate(BaseModel):
    block_type: Literal["objective", "variable", "decision", "missing_info"]
    reasoning: str
    goal_statement: Optional[str] = None
    success_criteria: Optional[list[str]] = None
    parameter_name: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    is_locked: Optional[bool] = None
    final_choice: Optional[str] = None
    rejected_alternatives: Optional[list[str]] = None
    blocking_parameter: Optional[str] = None
    impact: Optional[str] = None


class LLMBlockUpdate(LLMBlockCreate):
    id: uuid.UUID


class LLMPlannerOutput(BaseModel):
    blocks_to_create: list[LLMBlockCreate] = Field(default_factory=list)
    blocks_to_update: list[LLMBlockUpdate] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Lazy agent registries
# ---------------------------------------------------------------------------

CHUNK_SIZE = 10

_generate_agents: dict[str, Any] = {}
_planner_agents: dict[str, Any] = {}
_openscad_meeting_agents: dict[str, Any] = {}
_openscad_edit_agents: dict[str, Any] = {}
_openscad_fix_agents: dict[str, Any] = {}
_refine_agents: dict[str, Any] = {}


def _require_key(provider: str) -> None:
    cfg = PROVIDER_CONFIG[provider]
    if not os.getenv(cfg["key_env"], ""):
        raise RuntimeError(f"{cfg['key_env']} is not set. Add it to api/.env")


def _make_model(provider: str) -> Any:
    cfg = PROVIDER_CONFIG[provider]
    if "direct_base_url" in cfg:
        from pydantic_ai.models.openai import OpenAIModel
        from pydantic_ai.providers.openai import OpenAIProvider
        prov = OpenAIProvider(base_url=cfg["direct_base_url"], api_key=os.environ.get(cfg["key_env"], ""))
        return OpenAIModel(cfg["model_name"], provider=prov)
    if "gateway_route" in cfg:
        from pydantic_ai.models.openai import OpenAIModel
        from pydantic_ai.providers.gateway import gateway_provider as _gw
        gw = _gw(cfg["gateway_upstream"], route=cfg["gateway_route"])
        return OpenAIModel(cfg["model_name"], provider=gw)
    return cfg["model"]


def _get_generate_agent(provider: str) -> Agent:
    if provider not in _generate_agents:
        _generate_agents[provider] = Agent(
            _make_model(provider),
            system_prompt=GENERATE_SYSTEM_PROMPT,
            output_type=str,
            retries=1,
        )
    return _generate_agents[provider]


def _get_planner_agent(provider: str) -> Agent:
    if provider not in _planner_agents:
        _planner_agents[provider] = Agent(
            _make_model(provider),
            system_prompt=PLANNER_SYSTEM_PROMPT,
            output_type=str,
            retries=1,
        )
    return _planner_agents[provider]


def _get_openscad_meeting_agent(provider: str) -> Agent:
    if provider not in _openscad_meeting_agents:
        _openscad_meeting_agents[provider] = Agent(
            _make_model(provider),
            system_prompt=OPENSCAD_MEETING_SYSTEM_PROMPT,
            output_type=ModelIterationCreate,
            retries=1,
        )
    return _openscad_meeting_agents[provider]


def _get_openscad_edit_agent(provider: str) -> Agent:
    if provider not in _openscad_edit_agents:
        _openscad_edit_agents[provider] = Agent(
            _make_model(provider),
            system_prompt=OPENSCAD_EDIT_SYSTEM_PROMPT,
            output_type=OpenSCADEditOutput,
            retries=1,
        )
    return _openscad_edit_agents[provider]


def _get_openscad_fix_agent(provider: str) -> Agent:
    if provider not in _openscad_fix_agents:
        _openscad_fix_agents[provider] = Agent(
            _make_model(provider),
            system_prompt=OPENSCAD_FIX_SYSTEM_PROMPT,
            output_type=str,
            retries=1,
        )
    return _openscad_fix_agents[provider]


def _get_refine_agent(provider: str) -> Agent:
    if provider not in _refine_agents:
        _refine_agents[provider] = Agent(
            _make_model(provider),
            system_prompt=OPENSCAD_REFINE_SYSTEM_PROMPT,
            output_type=NativeOutput(ModelIterationCreate),
            retries=1,
        )
    return _refine_agents[provider]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _llm_block_to_content(b: LLMBlockCreate) -> AnyBlockContent:
    if b.block_type == "objective":
        return ObjectiveContent(
            goal_statement=b.goal_statement or "TBD",
            success_criteria=b.success_criteria or ["TBD"],
        )
    if b.block_type == "variable":
        return VariableContent(
            parameter_name=b.parameter_name or "unknown",
            value=b.value or 0.0,
            unit=b.unit or "",
            is_locked=b.is_locked or False,
        )
    if b.block_type == "decision":
        return DecisionContent(
            final_choice=b.final_choice or "TBD",
            rejected_alternatives=b.rejected_alternatives or [],
        )
    return MissingInfoContent(
        blocking_parameter=b.blocking_parameter or "unknown",
        impact=b.impact or "unknown",
    )


def _llm_output_to_planner_output(
    llm: LLMPlannerOutput,
    running_blocks: list[PlanBlock],
) -> PlannerOutput:
    block_versions = {b.id: b.version for b in running_blocks}
    creates = [
        PlanBlockCreate(content=_llm_block_to_content(b), reasoning=b.reasoning)
        for b in llm.blocks_to_create
    ]
    updates = []
    for b in llm.blocks_to_update:
        prev_version = block_versions.get(b.id, 1)
        updates.append(PlanBlock(
            id=b.id,
            content=_llm_block_to_content(b),
            reasoning=b.reasoning,
            version=prev_version + 1,
        ))
    return PlannerOutput(blocks_to_create=creates, blocks_to_update=updates)


def _strip_think_blocks(text: str) -> str:
    """Remove <think>...</think> blocks emitted by reasoning models before the answer."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)
    return text


def _model_settings(provider: str, temperature: float, max_tokens: int) -> Any:
    settings: dict[str, Any] = {"temperature": temperature, "max_tokens": max_tokens}
    if effort := PROVIDER_CONFIG[provider].get("reasoning_effort"):
        settings["openai_reasoning_effort"] = effort
        settings["extra_body"] = {
            "reasoning_effort": effort,
            "temperature": temperature,
            "top_p": 0.95,
        }
    return settings


def _build_meta(cfg: dict, latency_ms: float, usage: Any) -> dict:
    tps = None
    if usage.output_tokens and latency_ms > 0:
        tps = round(usage.output_tokens / (latency_ms / 1000), 1)
    return {
        "provider": cfg["label"],
        "model_name": cfg["model_name"],
        "latency_ms": round(latency_ms, 1),
        "usage": {
            "prompt_tokens": usage.input_tokens,
            "completion_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
        },
        "tokens_per_second": tps,
    }


# ---------------------------------------------------------------------------
# Public runner functions
# ---------------------------------------------------------------------------


async def run_generate(
    prompt: str,
    provider: str = "cerebras",
    temperature: float = 0.6,
    max_tokens: int = 8192,
    session_id: str | None = None,
) -> tuple[str, dict]:
    _require_key(provider)
    cfg = PROVIDER_CONFIG[provider]
    agent = _get_generate_agent(provider)

    if session_id is None:
        session_id = str(uuid.uuid4())

    # Fetch lessons from MuBit before calling the LLM
    mubit_context = await get_generation_context("openscad-generator", session_id)
    enriched_prompt = prompt
    if mubit_context:
        enriched_prompt = (
            f"LESSONS FROM PAST GENERATIONS (apply these to avoid past mistakes):\n"
            f"{mubit_context}\n\n"
            f"USER REQUEST:\n{prompt}"
        )

    t0 = time.perf_counter()
    result = await agent.run(
        enriched_prompt,
        model_settings=_model_settings(provider, temperature, max_tokens),
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    content = _strip_markdown_fences(result.output).strip()

    # Store the interaction in MuBit memory (fire-and-forget)
    asyncio.create_task(
        remember_generation("openscad-generator", session_id, prompt, content, cfg["model_name"])
    )

    meta = _build_meta(cfg, latency_ms, result.usage())
    meta["session_id"] = session_id
    return content, meta


async def run_planner(
    transcript: list[TranscriptEntry],
    existing_blocks: list[PlanBlock],
    provider: str = "cerebras",
    temperature: float = 0.6,
    max_tokens: int = 12000,
    session_id: str | None = None,
) -> tuple[PlannerOutput, dict]:
    _require_key(provider)
    cfg = PROVIDER_CONFIG[provider]
    agent = _get_planner_agent(provider)

    if session_id is None:
        session_id = str(uuid.uuid4())

    transcript_text = "\n".join(
        f"[{e.start_time:.1f}s-{e.end_time:.1f}s] {e.text}" for e in transcript
    ) or "(no transcript yet)"

    blocks_text = (
        "\n".join(b.model_dump_json() for b in existing_blocks) if existing_blocks else "(none)"
    )

    # Fetch lessons from MuBit
    mubit_context = await get_generation_context("planner", session_id)
    lessons_block = ""
    if mubit_context:
        lessons_block = f"LESSONS FROM PAST SESSIONS:\n{mubit_context}\n\n"

    prompt = (
        f"{lessons_block}"
        f"TRANSCRIPT:\n{transcript_text}\n\n"
        f"EXISTING BLOCKS:\n{blocks_text}\n\n"
        "Analyse the transcript and return structured plan block updates."
    )

    t0 = time.perf_counter()
    result = await asyncio.wait_for(
        agent.run(prompt, model_settings=_model_settings(provider, temperature, max_tokens)),
        timeout=90,
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    raw = _strip_markdown_fences(_strip_think_blocks(result.output))
    try:
        llm_out = LLMPlannerOutput.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as e:
        raise RuntimeError(f"Planner JSON parse failed: {e}\nRaw output: {raw[:500]}")
    output = _llm_output_to_planner_output(llm_out, existing_blocks)

    asyncio.create_task(
        remember_generation("planner", session_id, prompt[:500], str(result.output), cfg["model_name"])
    )

    return output, _build_meta(cfg, latency_ms, result.usage())


def _expand_multiline_entries(
    entries: list[TranscriptEntry],
) -> list[tuple[int, TranscriptEntry]]:
    """Expand entries with embedded newlines into (orig_index, sub-entry) pairs.

    A single pasted block like "line1\\nline2\\nline3" becomes three entries so
    the chunker treats each line as a separate utterance rather than one giant
    LLM call.  Original single-line entries pass through unchanged.
    """
    result: list[tuple[int, TranscriptEntry]] = []
    for orig_i, e in enumerate(entries):
        lines = [ln.strip() for ln in e.text.split("\n") if ln.strip()]
        if len(lines) <= 1:
            result.append((orig_i, e))
        else:
            duration = max((e.end_time - e.start_time) / len(lines), 0.1)
            for j, line in enumerate(lines):
                result.append((
                    orig_i,
                    TranscriptEntry(
                        text=line,
                        start_time=e.start_time + j * duration,
                        end_time=e.start_time + (j + 1) * duration,
                    ),
                ))
    return result


async def run_planner_chunked(
    transcript: list[TranscriptEntry],
    existing_blocks: list[PlanBlock],
    provider: str = "cerebras",
    temperature: float = 0.6,
    max_tokens: int = 12000,
) -> AsyncGenerator[tuple[str, Any], None]:
    """Yield SSE event tuples for each chunk of the transcript.

    Yields: ("chunk_start", dict), ("chunk_result", PlannerOutput),
            ("chunk_complete", dict), ("error", dict)
    """
    _require_key(provider)
    cfg = PROVIDER_CONFIG[provider]
    agent = _get_planner_agent(provider)
    settings = _model_settings(provider, temperature, max_tokens)

    # Expand entries that contain embedded newlines (e.g. a large pasted block) into
    # sub-entries so they are chunked like individual Scribe utterances.
    # Each item is (orig_index, TranscriptEntry) where orig_index is the position in
    # the original `transcript` list — used to report batch_offset_end in original-
    # entry units so the frontend cursor aligns correctly.
    expanded: list[tuple[int, TranscriptEntry]] = _expand_multiline_entries(transcript)
    chunks = [expanded[i: i + CHUNK_SIZE] for i in range(0, len(expanded), CHUNK_SIZE)]
    total_chunks = len(chunks)
    running_blocks = list(existing_blocks)

    for chunk_index, chunk in enumerate(chunks):
        last_orig_index = max(orig_i for orig_i, _ in chunk)
        batch_offset_end = min(last_orig_index + 1, len(transcript))

        yield ("chunk_start", {
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
            "batch_offset_end": batch_offset_end,
        })

        transcript_text = "\n".join(
            f"[{e.start_time:.1f}s-{e.end_time:.1f}s] {e.text}" for _, e in chunk
        )
        blocks_text = (
            "\n".join(b.model_dump_json() for b in running_blocks) if running_blocks else "(none)"
        )
        prompt = (
            f"TRANSCRIPT:\n{transcript_text}\n\n"
            f"EXISTING BLOCKS:\n{blocks_text}\n\n"
            "Analyse the transcript and return structured plan block updates."
        )

        try:
            result = await asyncio.wait_for(
                agent.run(prompt, model_settings=settings),
                timeout=90,
            )
        except asyncio.TimeoutError:
            logger.warning("planner chunk %d timed out for provider=%s", chunk_index, provider)
            yield ("error", {"detail": f"Chunk {chunk_index} timed out after 90s"})
            return
        except Exception as e:
            logger.warning("planner chunk %d agent error for provider=%s: %s", chunk_index, provider, e, exc_info=True)
            yield ("error", {"detail": f"Chunk {chunk_index} agent error: {e}"})
            return

        raw = _strip_markdown_fences(_strip_think_blocks(result.output))
        try:
            llm_out = LLMPlannerOutput.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning("planner chunk %d parse error for provider=%s: %s\nRaw: %s", chunk_index, provider, e, raw[:500])
            yield ("error", {"detail": f"Chunk {chunk_index} parse error: {e}"})
            return
        output = _llm_output_to_planner_output(llm_out, running_blocks)

        # Accumulate into running_blocks so later chunks see blocks from earlier ones
        for b in output.blocks_to_create:
            running_blocks.append(PlanBlock(**b.model_dump()))
        for b in output.blocks_to_update:
            for i, rb in enumerate(running_blocks):
                if rb.id == b.id:
                    running_blocks[i] = b
                    break

        asyncio.create_task(
            remember_generation("planner", str(uuid.uuid4()), prompt[:500], raw[:500], cfg["model_name"])
        )
        yield ("chunk_result", output)
        yield ("chunk_complete", {"chunk_index": chunk_index})


async def run_openscad_meeting(
    transcript: list[TranscriptEntry],
    blocks: list[PlanBlock],
    provider: str = "cerebras",
    temperature: float = 0.6,
    max_tokens: int = 16000,
    session_id: str | None = None,
) -> tuple[ModelIterationCreate, dict]:
    _require_key(provider)
    cfg = PROVIDER_CONFIG[provider]
    agent = _get_openscad_meeting_agent(provider)

    if session_id is None:
        session_id = str(uuid.uuid4())

    blocks_text = (
        "\n".join(b.model_dump_json() for b in blocks)
        if blocks
        else "(no blocks — generate a minimal parametric enclosure)"
    )
    recent_transcript = "\n".join(
        f"[{e.start_time:.1f}s] {e.text}" for e in transcript[-20:]
    ) or "(none)"

    # Fetch lessons from MuBit
    mubit_context = await get_generation_context("openscad-meeting", session_id)
    lessons_block = ""
    if mubit_context:
        lessons_block = f"LESSONS FROM PAST GENERATIONS:\n{mubit_context}\n\n"

    prompt = (
        f"{lessons_block}"
        f"PLAN BLOCKS:\n{blocks_text}\n\n"
        f"RECENT TRANSCRIPT:\n{recent_transcript}\n\n"
        "Generate a complete, compilable OpenSCAD script for this enclosure."
    )

    t0 = time.perf_counter()
    result = await asyncio.wait_for(
        agent.run(prompt, model_settings=_model_settings(provider, temperature, max_tokens)),
        timeout=240,
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    asyncio.create_task(
        remember_generation(
            "openscad-meeting", session_id, prompt[:500],
            result.output.script if hasattr(result.output, "script") else str(result.output),
            cfg["model_name"],
        )
    )

    meta = _build_meta(cfg, latency_ms, result.usage())
    meta["session_id"] = session_id
    return result.output, meta


async def run_openscad_edit(
    current_script: str,
    changed_blocks: list[PlanBlock],
    provider: str = "cerebras",
    max_tokens: int = 8192,
) -> tuple[str, list[ScriptEdit], dict]:
    """Apply targeted edits to an existing OpenSCAD script based on changed blocks.

    Returns (patched_script, edits_applied, meta).
    """
    _require_key(provider)
    cfg = PROVIDER_CONFIG[provider]
    agent = _get_openscad_edit_agent(provider)

    blocks_text = "\n".join(b.model_dump_json() for b in changed_blocks) or "(none)"
    prompt = (
        f"CURRENT SCRIPT:\n{current_script}\n\n"
        f"CHANGED BLOCKS:\n{blocks_text}\n\n"
        "Return a minimal edit list to update the script for these changed blocks."
    )

    t0 = time.perf_counter()
    result = await asyncio.wait_for(
        agent.run(prompt, model_settings=_model_settings(provider, 0.6, max_tokens)),
        timeout=120,
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    output: OpenSCADEditOutput = result.output
    patched = current_script
    for edit in output.edits:
        patched = patched.replace(edit.search, edit.replace, 1)

    meta = _build_meta(cfg, latency_ms, result.usage())
    meta["reasoning"] = output.reasoning
    meta["applied_lessons"] = output.applied_lessons
    return patched, output.edits, meta


async def run_openscad_fix(
    current_script: str,
    stderr: str,
    provider: str = "cerebras",
    max_tokens: int = 16000,
) -> tuple[str, dict]:
    """Ask the LLM to fix a script given OpenSCAD compiler stderr output.

    Returns (fixed_script, meta).
    """
    _require_key(provider)
    cfg = PROVIDER_CONFIG[provider]
    agent = _get_openscad_fix_agent(provider)

    prompt = (
        f"CURRENT SCRIPT:\n{current_script}\n\n"
        f"COMPILER STDERR:\n{stderr}\n\n"
        "Return the complete corrected OpenSCAD script."
    )

    t0 = time.perf_counter()
    result = await asyncio.wait_for(
        agent.run(prompt, model_settings=_model_settings(provider, 0.5, max_tokens)),
        timeout=120,
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    fixed = _strip_markdown_fences(result.output).strip()
    return fixed, _build_meta(cfg, latency_ms, result.usage())


async def run_openscad_refine(
    blocks: list[PlanBlock],
    current_script: str | None,
    provider: str = "anthropic",
    max_tokens: int = 16384,
    session_id: str | None = None,
    previous_compile_ok: bool | None = None,
    previous_compile_stderr: str | None = None,
) -> tuple[ModelIterationCreate, dict]:
    """Use Claude Sonnet with adaptive extended thinking to produce a high-quality OpenSCAD model.

    Returns (iteration_create, meta).
    """
    _require_key(provider)
    cfg = PROVIDER_CONFIG[provider]
    agent = _get_refine_agent(provider)

    if session_id is None:
        session_id = str(uuid.uuid4())

    blocks_text = (
        "\n".join(b.model_dump_json() for b in blocks) if blocks else "(no blocks)"
    )
    script_section = (
        f"CURRENT DRAFT (use as reference, improve freely):\n{current_script}"
        if current_script
        else "(no previous script — generate from scratch)"
    )
    if previous_compile_ok is False:
        filtered_err = _filter_openscad_stderr(previous_compile_stderr)
        compile_section = (
            "PREVIOUS COMPILE RESULT: FAILED\n"
            f"Errors to fix:\n{filtered_err or '(no ERROR: lines — may be a geometry/render issue)'}\n\n"
        )
    elif previous_compile_ok is True:
        compile_section = "PREVIOUS COMPILE RESULT: OK (improve quality, don't break what works)\n\n"
    else:
        compile_section = ""

    prompt = (
        f"PLAN BLOCKS:\n{blocks_text}\n\n"
        f"{script_section}\n\n"
        f"{compile_section}"
        "Produce a complete, high-quality OpenSCAD model."
    )

    mubit_context = await get_generation_context("openscad-refine", session_id)
    if mubit_context:
        prompt = f"LESSONS FROM PAST REFINEMENTS:\n{mubit_context}\n\n" + prompt

    # Sonnet 4.6: adaptive thinking + low effort; temperature disallowed
    model_settings = AnthropicModelSettings(
        max_tokens=max_tokens,
        anthropic_thinking={"type": "adaptive"},
        anthropic_effort="low",
    )

    t0 = time.perf_counter()
    result = await asyncio.wait_for(
        agent.run(prompt, model_settings=model_settings),
        timeout=300,
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    asyncio.create_task(
        remember_generation("openscad-refine", session_id, prompt[:500], result.output.script, cfg["model_name"])
    )

    meta = _build_meta(cfg, latency_ms, result.usage())
    meta["session_id"] = session_id
    return result.output, meta


async def run_fea_analysis(
    script: str,
    blocks: list[PlanBlock],
    provider: str = "groq",
    max_tokens: int = 16384,
) -> tuple[dict, dict]:
    """Run FEA-style structural analysis on an OpenSCAD script.

    Returns (analysis_dict with stress_script, meta).
    """
    _require_key(provider)
    cfg = PROVIDER_CONFIG[provider]
    agent = _get_fea_agent(provider)

    blocks_text = (
        "\n".join(b.model_dump_json() for b in blocks) if blocks else "(no blocks)"
    )
    prompt = (
        f"OPENSCAD SCRIPT:\n{script}\n\n"
        f"DESIGN PLAN BLOCKS:\n{blocks_text}\n\n"
        "Perform a thorough FEA-style structural analysis. Return the JSON with "
        "both the report fields AND the stress_script (colour heat-mapped OpenSCAD)."
    )

    t0 = time.perf_counter()
    result = await asyncio.wait_for(
        agent.run(prompt, model_settings=_model_settings(provider, 0.3, max_tokens)),
        timeout=180,
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    raw = _strip_markdown_fences(_strip_think_blocks(result.output)).strip()
    try:
        analysis = json.loads(raw)
    except json.JSONDecodeError:
        # LLMs often put literal newlines/tabs inside JSON string values — fix them
        # Replace unescaped control characters inside JSON strings
        def _fix_json_strings(s: str) -> str:
            # Replace literal newlines/tabs that aren't already escaped
            s = s.replace("\\\n", "\\n")  # preserve already-escaped
            s = s.replace("\n", "\\n")
            s = s.replace("\\\t", "\\t")
            s = s.replace("\t", "\\t")
            s = s.replace("\r", "\\r")
            return s
        try:
            analysis = json.loads(_fix_json_strings(raw))
        except json.JSONDecodeError as e2:
            raise RuntimeError(f"FEA analysis JSON parse failed: {e2}\nRaw: {raw[:500]}")

    return analysis, _build_meta(cfg, latency_ms, result.usage())


# ---------------------------------------------------------------------------
# CadQuery runner functions
# ---------------------------------------------------------------------------


async def run_cadquery_meeting(
    transcript: list[TranscriptEntry],
    blocks: list[PlanBlock],
    provider: str = "anthropic",
    temperature: float = 0.5,
    max_tokens: int = 8192,
) -> tuple[ModelIterationCreate, dict]:
    _require_key(provider)
    cfg = PROVIDER_CONFIG[provider]
    agent = _get_cadquery_meeting_agent(provider)

    blocks_text = (
        "\n".join(b.model_dump_json() for b in blocks)
        if blocks
        else "(no blocks — generate a minimal parametric enclosure)"
    )
    recent_transcript = "\n".join(
        f"[{e.start_time:.1f}s] {e.text}" for e in transcript[-20:]
    ) or "(none)"

    prompt = (
        f"PLAN BLOCKS:\n{blocks_text}\n\n"
        f"RECENT TRANSCRIPT:\n{recent_transcript}\n\n"
        "Generate a complete, executable CadQuery Python script for this design."
    )

    t0 = time.perf_counter()
    result = await asyncio.wait_for(
        agent.run(prompt, model_settings=_model_settings(provider, temperature, max_tokens)),
        timeout=240,
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    return result.output, _build_meta(cfg, latency_ms, result.usage())


async def run_cadquery_fix(
    current_script: str,
    stderr: str,
    provider: str = "anthropic",
    max_tokens: int = 8192,
) -> tuple[str, dict]:
    _require_key(provider)
    cfg = PROVIDER_CONFIG[provider]
    agent = _get_cadquery_fix_agent(provider)

    prompt = (
        f"CURRENT SCRIPT:\n{current_script}\n\n"
        f"ERROR OUTPUT:\n{stderr}\n\n"
        "Return the complete corrected CadQuery Python script."
    )

    t0 = time.perf_counter()
    result = await asyncio.wait_for(
        agent.run(prompt, model_settings=_model_settings(provider, 0.2, max_tokens)),
        timeout=120,
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    fixed = _strip_markdown_fences(result.output).strip()
    return fixed, _build_meta(cfg, latency_ms, result.usage())
