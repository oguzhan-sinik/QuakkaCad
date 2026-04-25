from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModelSettings
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from schemas import ModelIterationCreate, PlanBlock, PlanBlockCreate, TranscriptEntry

load_dotenv(Path(__file__).parent / ".env")

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

GENERATE_SYSTEM_PROMPT = (Path(__file__).parent / "prompt.md").read_text()

PLANNER_SYSTEM_PROMPT = """\
You are the MuBit Planner Agent. Parse hackathon meeting transcripts and extract \
structured plan blocks for a CAD design project.

Given the current transcript and existing blocks, return:
- blocks_to_create: new blocks for information not yet captured
- blocks_to_update: modified existing blocks (must include the correct UUID)

Block types and when to use them:
  objective    - physical build goal; populate success_criteria as a strict list
  variable     - a numeric parameter (dimensions, voltages, weights); set is_locked=true
                 ONLY when the team explicitly agreed on that exact value
  decision     - a design choice; list rejected_alternatives explicitly mentioned
  missing_info - a required parameter not yet agreed upon; explain the downstream impact

Rules:
- Increment version when updating an existing block
- reasoning must be ≥ 10 chars and cite specific transcript evidence
- Never fabricate values; if a number is uncertain, use missing_info instead
- applied_lessons: cite any past mistakes or heuristics you're applying\
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
- reasoning must explain your geometric decisions
- applied_lessons: list specific CAD heuristics or past compilation errors avoided\
"""

# ---------------------------------------------------------------------------
# Provider config
# ---------------------------------------------------------------------------

_mercury_model = OpenAIChatModel(
    "mercury-2",
    provider=OpenAIProvider(
        base_url="https://api.inceptionlabs.ai/v1",
        api_key=os.getenv("INCEPTION_API_KEY", ""),
    ),
)

_cerebras_model = OpenAIChatModel(
    "zai-glm-4.7",
    provider=OpenAIProvider(
        base_url="https://api.cerebras.ai/v1",
        api_key=os.getenv("CEREBRAS_API_KEY", ""),
    ),
)

PROVIDER_CONFIG: dict[str, dict] = {
    "mercury": {
        "model": _mercury_model,
        "model_name": "mercury-2",
        "label": "Inception Mercury 2",
        "key_env": "INCEPTION_API_KEY",
    },
    "cerebras": {
        "model": _cerebras_model,
        "model_name": "zai-glm-4.7",
        "label": "Cerebras",
        "key_env": "CEREBRAS_API_KEY",
    },
    "pydantic": {
        "model": "gateway/anthropic:claude-opus-4-7",
        "model_name": "gateway/anthropic:claude-opus-4-7",
        "label": "Pydantic Gateway (Claude Opus 4.7)",
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


# ---------------------------------------------------------------------------
# Lazy agent registries
# ---------------------------------------------------------------------------

_generate_agents: dict[str, Any] = {}
_planner_agents: dict[str, Any] = {}
_openscad_meeting_agents: dict[str, Any] = {}


def _require_key(provider: str) -> None:
    cfg = PROVIDER_CONFIG[provider]
    if not os.getenv(cfg["key_env"], ""):
        raise RuntimeError(f"{cfg['key_env']} is not set. Add it to api/.env")


def _get_generate_agent(provider: str) -> Agent:
    if provider not in _generate_agents:
        cfg = PROVIDER_CONFIG[provider]
        _generate_agents[provider] = Agent(
            cfg["model"],
            system_prompt=GENERATE_SYSTEM_PROMPT,
            output_type=str,
        )
    return _generate_agents[provider]


def _get_planner_agent(provider: str) -> Agent:
    if provider not in _planner_agents:
        cfg = PROVIDER_CONFIG[provider]
        _planner_agents[provider] = Agent(
            cfg["model"],
            system_prompt=PLANNER_SYSTEM_PROMPT,
            output_type=PlannerOutput,
        )
    return _planner_agents[provider]


def _get_openscad_meeting_agent(provider: str) -> Agent:
    if provider not in _openscad_meeting_agents:
        cfg = PROVIDER_CONFIG[provider]
        _openscad_meeting_agents[provider] = Agent(
            cfg["model"],
            system_prompt=OPENSCAD_MEETING_SYSTEM_PROMPT,
            output_type=ModelIterationCreate,
        )
    return _openscad_meeting_agents[provider]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    if provider == "pydantic":
        # Claude Opus 4.7: temperature is not supported; cache the system prompt for 1 h
        return AnthropicModelSettings(
            max_tokens=max_tokens,
            anthropic_cache_instructions="1h",
        )
    return {"temperature": temperature, "max_tokens": max_tokens}


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
    provider: str = "mercury",
    temperature: float = 0.75,
    max_tokens: int = 8192,
) -> tuple[str, dict]:
    _require_key(provider)
    cfg = PROVIDER_CONFIG[provider]
    agent = _get_generate_agent(provider)

    t0 = time.perf_counter()
    result = await agent.run(
        prompt,
        model_settings=_model_settings(provider, temperature, max_tokens),
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    content = _strip_markdown_fences(result.output).strip()
    return content, _build_meta(cfg, latency_ms, result.usage())


async def run_planner(
    transcript: list[TranscriptEntry],
    existing_blocks: list[PlanBlock],
    provider: str = "pydantic",
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> tuple[PlannerOutput, dict]:
    _require_key(provider)
    cfg = PROVIDER_CONFIG[provider]
    agent = _get_planner_agent(provider)

    transcript_text = "\n".join(
        f"[{e.start_time:.1f}s-{e.end_time:.1f}s] {e.text}" for e in transcript
    ) or "(no transcript yet)"

    blocks_text = (
        "\n".join(b.model_dump_json() for b in existing_blocks) if existing_blocks else "(none)"
    )

    prompt = (
        f"TRANSCRIPT:\n{transcript_text}\n\n"
        f"EXISTING BLOCKS:\n{blocks_text}\n\n"
        "Analyse the transcript and return structured plan block updates."
    )

    t0 = time.perf_counter()
    result = await agent.run(
        prompt,
        model_settings=_model_settings(provider, temperature, max_tokens),
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    return result.output, _build_meta(cfg, latency_ms, result.usage())


async def run_openscad_meeting(
    transcript: list[TranscriptEntry],
    blocks: list[PlanBlock],
    provider: str = "pydantic",
    temperature: float = 0.5,
    max_tokens: int = 8192,
) -> tuple[ModelIterationCreate, dict]:
    _require_key(provider)
    cfg = PROVIDER_CONFIG[provider]
    agent = _get_openscad_meeting_agent(provider)

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
        "Generate a complete, compilable OpenSCAD script for this enclosure."
    )

    t0 = time.perf_counter()
    result = await agent.run(
        prompt,
        model_settings=_model_settings(provider, temperature, max_tokens),
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    return result.output, _build_meta(cfg, latency_ms, result.usage())
