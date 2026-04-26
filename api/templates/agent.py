"""Template classification agent — routes prompts to assembly specs."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from pydantic import TypeAdapter
from pydantic_ai import Agent

from .models import (
    AssemblySpec,
    BushingAssemblySpec,
    FinnedRocketBodySpec,
    FlangedTubeSpec,
    GearTrainSpec,
)

logger = logging.getLogger(__name__)

_spec_adapter = TypeAdapter(AssemblySpec)

TEMPLATE_SYSTEM_PROMPT = """\
You are a mechanical parts classifier. Given a natural-language description, \
output a JSON object matching one of these assembly templates.

Return ONLY valid JSON — no markdown fences, no prose.

TEMPLATES (use assembly_type as discriminator):

1. "finned_rocket_body" — fields: reasoning, assembly_type, tube_outer_d, tube_wall, \
tube_length, ring_count, ring_width, ring_radial_thickness, ring_spacing, fin_count, \
fin_root_chord, fin_tip_chord, fin_height, fin_sweep, fin_thickness, fins_through_rings

2. "gear_train" — fields: reasoning, assembly_type, gear_count, teeth (array of ints), \
module_val, thickness, bore_d
Use for LINEAR gear trains only (gears side by side on parallel axes).

3. "planetary_gear" — fields: reasoning, assembly_type, sun_teeth, planet_teeth, \
planet_count, module_val, thickness, bore_d, include_ring_gear
Use for PLANETARY gear sets (sun gear + orbiting planets + ring gear). \
Ring teeth are auto-computed as sun_teeth + 2*planet_teeth.

5. "bushing_assembly" — fields: reasoning, assembly_type, bore_d, outer_d, length, \
flange, flange_outer_d, flange_thickness

6. "flanged_tube" — fields: reasoning, assembly_type, tube_outer_d, tube_inner_d, \
tube_length, flange_outer_d, flange_thickness, bolt_count, bolt_circle_d, bolt_hole_d, \
flange_both_ends

RULES:
- ALL dimensions in millimeters
- If the user omits a dimension, use sensible engineering defaults
- "reasoning" must briefly explain your choices
- Pick the CLOSEST matching assembly_type
- If "planetary", "sun gear", "planet gear", "epicyclic" → planetary_gear
- If "gear train", "gearbox", "reduction" (linear arrangement) → gear_train
- Convert units: "1m"→1000, "2 inches"→50.8

EXAMPLES:

Input: "90mm motor tube, 3mm wall, 200mm long, 4 fins"
{"reasoning":"Standard rocket motor tube","assembly_type":"finned_rocket_body",\
"tube_outer_d":90,"tube_wall":3,"tube_length":200,"ring_count":0,"ring_width":10,\
"ring_radial_thickness":4,"fin_count":4,"fin_root_chord":80,"fin_tip_chord":30,\
"fin_height":60,"fin_sweep":30,"fin_thickness":2,"fins_through_rings":false}

Input: "3-gear train, module 1.5, 20-40-60 teeth, 5mm thick"
{"reasoning":"3-stage reduction","assembly_type":"gear_train","gear_count":3,\
"teeth":[20,40,60],"module_val":1.5,"thickness":5,"bore_d":5}

Input: "planetary gear set, 20-tooth sun, 15-tooth planets, 3 planets"
{"reasoning":"Standard planetary with 3 planets","assembly_type":"planetary_gear",\
"sun_teeth":20,"planet_teeth":15,"planet_count":3,"module_val":2,"thickness":8,\
"bore_d":5,"include_ring_gear":true}

Input: "ball bushing 8mm bore, 15mm OD, 24mm long"
{"reasoning":"Standard bushing dimensions","assembly_type":"bushing_assembly",\
"bore_d":8,"outer_d":15,"length":24,"flange":false}

Input: "flanged tube 50mm OD, 30mm ID, 100mm, 6 M5 bolts"
{"reasoning":"Flanged pipe section","assembly_type":"flanged_tube","tube_outer_d":50,\
"tube_inner_d":30,"tube_length":100,"flange_outer_d":80,"flange_thickness":5,\
"bolt_count":6,"bolt_circle_d":65,"bolt_hole_d":5.5,"flange_both_ends":false}
"""

_template_agents: dict[str, Any] = {}


def _get_template_agent(provider: str = "anthropic") -> Agent:
    if provider not in _template_agents:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from agents import PROVIDER_CONFIG, _require_key, _make_model
        _require_key(provider)
        _template_agents[provider] = Agent(
            _make_model(provider),
            system_prompt=TEMPLATE_SYSTEM_PROMPT,
            output_type=str,
            retries=1,
        )
    return _template_agents[provider]


def _strip_fences(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        lines = s.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines)
    return s.strip()


def _strip_think(text: str) -> str:
    import re
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


async def run_template_agent(
    prompt: str,
    provider: str = "anthropic",
) -> tuple[AssemblySpec, dict]:
    """Classify a prompt into an AssemblySpec via JSON parsing.

    Fetches MuBit template library context before the LLM call to surface
    parameter schemas and past compilation lessons. Records the interaction
    in MuBit memory after classification.

    Returns (spec, meta_dict).
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agents import PROVIDER_CONFIG, _require_key, _build_meta, _model_settings
    from mubit_client import get_template_context

    _require_key(provider)
    cfg = PROVIDER_CONFIG[provider]
    agent = _get_template_agent(provider)

    session_id = str(uuid.uuid4())

    # Fetch relevant template context from MuBit before classification.
    # This surfaces parameter ranges, constraints, and past lessons so the
    # LLM makes better-informed parameter choices. Falls back gracefully to
    # an empty string if MuBit is unavailable.
    mubit_context = await get_template_context(prompt)
    enriched_prompt = prompt
    if mubit_context:
        enriched_prompt = (
            f"AVAILABLE TEMPLATE KNOWLEDGE (parameter schemas, constraints, lessons):\n"
            f"{mubit_context}\n\n"
            f"USER REQUEST:\n{prompt}"
        )

    t0 = time.perf_counter()
    result = await asyncio.wait_for(
        agent.run(enriched_prompt, model_settings=_model_settings(provider, 0.3, 4096)),
        timeout=30,
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    raw = _strip_fences(_strip_think(result.output))
    spec = None
    last_error = None

    for attempt in range(2):  # initial + 1 retry
        if attempt > 0:
            # Retry with validation error as feedback
            retry_prompt = (
                f"Your previous output had a validation error:\n{last_error}\n\n"
                f"Fix the values and return valid JSON for: {prompt}"
            )
            result = await asyncio.wait_for(
                agent.run(retry_prompt, model_settings=_model_settings(provider, 0.3, 4096)),
                timeout=30,
            )
            latency_ms += (time.perf_counter() - t0) * 1000
            raw = _strip_fences(_strip_think(result.output))

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            last_error = f"Invalid JSON: {e}"
            continue

        try:
            spec = _spec_adapter.validate_python(data)
            break
        except Exception as e:
            last_error = str(e)
            continue

    if spec is None:
        raise RuntimeError(f"Template spec validation failed after retry: {last_error}")

    meta = _build_meta(cfg, latency_ms, result.usage())
    meta["assembly_type"] = spec.assembly_type
    meta["session_id"] = session_id
    logger.info(
        "Template agent classified as %s in %.0fms",
        spec.assembly_type, latency_ms,
    )

    return spec, meta
