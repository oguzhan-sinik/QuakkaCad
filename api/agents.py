from __future__ import annotations

import asyncio
import os
import time
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModelSettings

from mubit_client import get_generation_context, remember_generation
from schemas import ModelIterationCreate, PlanBlock, PlanBlockCreate, ScriptEdit, TranscriptEntry

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

OPENSCAD_EDIT_SYSTEM_PROMPT = """\
You are the MuBit OpenSCAD Edit Agent. Given an existing valid OpenSCAD script and \
a set of changed plan blocks, return a minimal list of search-and-replace edits.

Rules:
- Prefer updating variable declarations at the top (e.g. board_length = 102; → board_length = 110;)
- Only touch geometry when a decision or objective block explicitly changed the form factor
- Each search string must match exactly one location in the script
- Do not rewrite the whole file — only the minimum edits to reflect the changed blocks
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
- reasoning must explain your geometric decisions
- applied_lessons: list specific CAD heuristics or past compilation errors avoided\
"""

# ---------------------------------------------------------------------------
# Provider config
# ---------------------------------------------------------------------------

PROVIDER_CONFIG: dict[str, dict] = {
    "pydantic": {
        "model": "gateway/anthropic:claude-opus-4-7",
        "model_name": "gateway/anthropic:claude-opus-4-7",
        "label": "Pydantic Gateway (Claude Opus 4.7)",
        "key_env": "PYDANTIC_AI_GATEWAY_API_KEY",
    },
    "pydantic-fast": {
        "model": "gateway/anthropic:claude-sonnet-4-6",
        "model_name": "gateway/anthropic:claude-sonnet-4-6",
        "label": "Pydantic Gateway (Claude Sonnet 4.6)",
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


# ---------------------------------------------------------------------------
# Lazy agent registries
# ---------------------------------------------------------------------------

CHUNK_SIZE = 10

_generate_agents: dict[str, Any] = {}
_planner_agents: dict[str, Any] = {}
_openscad_meeting_agents: dict[str, Any] = {}
_openscad_edit_agents: dict[str, Any] = {}


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


def _get_openscad_edit_agent(provider: str) -> Agent:
    if provider not in _openscad_edit_agents:
        cfg = PROVIDER_CONFIG[provider]
        _openscad_edit_agents[provider] = Agent(
            cfg["model"],
            system_prompt=OPENSCAD_EDIT_SYSTEM_PROMPT,
            output_type=OpenSCADEditOutput,
        )
    return _openscad_edit_agents[provider]


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
        # Opus 4.7: temperature not supported; cache system prompt for 1h
        return AnthropicModelSettings(
            max_tokens=max_tokens,
            anthropic_cache_instructions="1h",
        )
    if provider == "pydantic-fast":
        # Sonnet 4.6: temperature supported; cache system prompt for 1h
        return AnthropicModelSettings(
            max_tokens=max_tokens,
            temperature=temperature,
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
    provider: str = "pydantic",
    temperature: float = 0.75,
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
    provider: str = "pydantic",
    temperature: float = 0.3,
    max_tokens: int = 4096,
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

    asyncio.create_task(
        remember_generation("planner", session_id, prompt[:500], str(result.output), cfg["model_name"])
    )

    return result.output, _build_meta(cfg, latency_ms, result.usage())


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
    provider: str = "pydantic-fast",
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> AsyncGenerator[tuple[str, Any], None]:
    """Yield SSE event tuples for each chunk of the transcript.

    Yields: ("chunk_start", dict), ("chunk_result", PlannerOutput),
            ("chunk_complete", dict), ("error", dict)
    """
    _require_key(provider)
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
            output: PlannerOutput = result.output
        except asyncio.TimeoutError:
            yield ("error", {"detail": f"Chunk {chunk_index} timed out after 90s"})
            return
        except Exception as e:
            yield ("error", {"detail": f"Chunk {chunk_index} agent error: {e}"})
            return

        # Accumulate into running_blocks so later chunks see blocks from earlier ones
        for b in output.blocks_to_create:
            running_blocks.append(PlanBlock(**b.model_dump()))
        for b in output.blocks_to_update:
            for i, rb in enumerate(running_blocks):
                if rb.id == b.id:
                    running_blocks[i] = b
                    break

        yield ("chunk_result", output)
        yield ("chunk_complete", {"chunk_index": chunk_index})


async def run_openscad_meeting(
    transcript: list[TranscriptEntry],
    blocks: list[PlanBlock],
    provider: str = "pydantic",
    temperature: float = 0.5,
    max_tokens: int = 8192,
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
    provider: str = "pydantic",
    max_tokens: int = 2048,
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
        agent.run(prompt, model_settings=_model_settings(provider, 0.3, max_tokens)),
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
