"""Render pipeline: prompt → agent → spec → compose → .scad source."""

from __future__ import annotations

import asyncio
import logging

from .agent import run_template_agent
from .assemblies import dispatch_compose
from .models import AssemblySpec

logger = logging.getLogger(__name__)


async def render_from_prompt(
    prompt: str,
    provider: str = "anthropic",
) -> tuple[AssemblySpec, str, dict]:
    """Full pipeline: prompt → AssemblySpec → .scad source string.

    Returns (spec, scad_source, meta).
    The frontend WASM worker handles compilation.
    """
    spec, meta = await run_template_agent(prompt, provider=provider)
    scad_source = dispatch_compose(spec)
    meta["scad_length"] = len(scad_source)
    logger.info(
        "Template render complete: %s, %d chars SCAD",
        spec.assembly_type, len(scad_source),
    )

    # Record the generation trace into the shared MuBit library session so
    # future get_template_context() calls can learn from parameter choices.
    from mubit_client import remember_template_generation
    asyncio.create_task(
        remember_template_generation(
            prompt=prompt,
            assembly_type=spec.assembly_type,
            scad_length=len(scad_source),
            model_used=meta.get("model_name", "unknown"),
        )
    )

    return spec, scad_source, meta
