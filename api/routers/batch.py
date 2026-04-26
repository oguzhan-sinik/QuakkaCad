"""Batch template generation endpoints.

Two modes:
  POST /api/batch/template            — mixed spec items (free) + prompt items (LLM)
  POST /api/batch/template/programmatic — pure parametric sweep, no LLM
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from mubit_client import remember_template_generation
from templates.assemblies import dispatch_compose
from templates.agent import _spec_adapter
from templates.models import AssemblySpec
from templates.render import compose_from_spec, render_from_prompt, _build_diverse_spec_library

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/batch", tags=["batch"])

# Cap parallel LLM calls to avoid rate-limit errors (Anthropic TPM).
_LLM_SEMAPHORE = asyncio.Semaphore(5)


# ── Request / response models ─────────────────────────────────────────────────

class BatchItem(BaseModel):
    mode: Literal["spec", "prompt"] = "spec"
    spec: dict | None = Field(default=None, description="Pre-built AssemblySpec dict (mode=spec)")
    prompt: str | None = Field(default=None, description="Natural-language prompt (mode=prompt)")
    label: str | None = Field(default=None, description="Optional tracking label")


class BatchTemplateRequest(BaseModel):
    items: list[BatchItem] = Field(min_length=1, max_length=200)
    provider: str = Field(default="anthropic")
    include_scad: bool = Field(default=True, description="Set false to omit SCAD bodies and reduce response size")
    seed_mubit: bool = Field(default=True, description="Record all successes into MuBit")


class BatchResultItem(BaseModel):
    index: int
    label: str | None
    assembly_type: str | None
    scad_source: str | None
    scad_length: int
    error: str | None
    cost_zone: Literal["free", "llm"]
    latency_ms: float


class BatchTemplateResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    free_tier_count: int
    llm_tier_count: int
    results: list[BatchResultItem]
    total_latency_ms: float


class ProgrammaticBatchRequest(BaseModel):
    count: int = Field(ge=1, le=500, default=20)
    assembly_types: list[str] | None = Field(default=None, description="Subset of template types; None = all 5")
    seed: int = Field(default=42, description="Deterministic seed (affects sweep distribution)")
    include_scad: bool = Field(default=True)
    seed_mubit: bool = Field(default=True)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/template", response_model=BatchTemplateResponse)
async def batch_template(body: BatchTemplateRequest) -> BatchTemplateResponse:
    """Generate multiple objects from a mix of pre-built specs and natural-language prompts.

    Spec items bypass the LLM entirely (free, sub-millisecond).
    Prompt items fan out in parallel behind a rate-limit semaphore.
    """
    t_start = time.perf_counter()
    results: list[BatchResultItem | None] = [None] * len(body.items)

    spec_indices = [(i, item) for i, item in enumerate(body.items) if item.mode == "spec"]
    prompt_indices = [(i, item) for i, item in enumerate(body.items) if item.mode == "prompt"]

    # Free tier — synchronous, no I/O
    for i, item in spec_indices:
        t0 = time.perf_counter()
        try:
            if not item.spec:
                raise ValueError("spec is required for mode='spec'")
            spec: AssemblySpec = _spec_adapter.validate_python(item.spec)
            scad = dispatch_compose(spec)
            results[i] = BatchResultItem(
                index=i, label=item.label,
                assembly_type=spec.assembly_type,
                scad_source=scad if body.include_scad else None,
                scad_length=len(scad), error=None, cost_zone="free",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
        except Exception as exc:
            results[i] = BatchResultItem(
                index=i, label=item.label, assembly_type=None,
                scad_source=None, scad_length=0, error=str(exc),
                cost_zone="free", latency_ms=(time.perf_counter() - t0) * 1000,
            )

    # LLM tier — parallel with semaphore
    if prompt_indices:
        async def _do_prompt(i: int, item: BatchItem) -> BatchResultItem:
            t0 = time.perf_counter()
            async with _LLM_SEMAPHORE:
                try:
                    if not item.prompt:
                        raise ValueError("prompt is required for mode='prompt'")
                    spec, scad, _meta = await render_from_prompt(item.prompt, provider=body.provider)
                    return BatchResultItem(
                        index=i, label=item.label,
                        assembly_type=spec.assembly_type,
                        scad_source=scad if body.include_scad else None,
                        scad_length=len(scad), error=None, cost_zone="llm",
                        latency_ms=(time.perf_counter() - t0) * 1000,
                    )
                except Exception as exc:
                    return BatchResultItem(
                        index=i, label=item.label, assembly_type=None,
                        scad_source=None, scad_length=0, error=str(exc),
                        cost_zone="llm", latency_ms=(time.perf_counter() - t0) * 1000,
                    )

        llm_tasks = [asyncio.create_task(_do_prompt(i, item)) for i, item in prompt_indices]
        llm_results = await asyncio.gather(*llm_tasks, return_exceptions=True)
        for (i, _), r in zip(prompt_indices, llm_results):
            if isinstance(r, Exception):
                results[i] = BatchResultItem(
                    index=i, label=None, assembly_type=None, scad_source=None,
                    scad_length=0, error=str(r), cost_zone="llm", latency_ms=0,
                )
            else:
                results[i] = r  # type: ignore[assignment]

    if body.seed_mubit:
        for r in results:
            if r and r.error is None and r.assembly_type:
                asyncio.create_task(remember_template_generation(
                    prompt=f"[batch] {r.label or r.assembly_type}",
                    assembly_type=r.assembly_type,
                    scad_length=r.scad_length,
                    model_used=r.cost_zone,
                ))

    valid = [r for r in results if r is not None]
    succeeded = sum(1 for r in valid if r.error is None)
    return BatchTemplateResponse(
        total=len(body.items),
        succeeded=succeeded,
        failed=len(valid) - succeeded,
        free_tier_count=len(spec_indices),
        llm_tier_count=len(prompt_indices),
        results=valid,
        total_latency_ms=(time.perf_counter() - t_start) * 1000,
    )


@router.post("/template/programmatic", response_model=BatchTemplateResponse)
async def batch_template_programmatic(body: ProgrammaticBatchRequest) -> BatchTemplateResponse:
    """Generate N diverse objects via parametric sweep — no LLM, no cost.

    Uses linear interpolation across valid parameter ranges for each assembly
    type. Deterministic: same count + seed always produces the same objects.
    """
    t_start = time.perf_counter()

    specs = _build_diverse_spec_library(
        count=body.count,
        assembly_types=body.assembly_types,
        seed=body.seed,
    )

    results: list[BatchResultItem] = []
    for i, spec in enumerate(specs):
        t0 = time.perf_counter()
        try:
            scad = dispatch_compose(spec)
            results.append(BatchResultItem(
                index=i, label=None,
                assembly_type=spec.assembly_type,
                scad_source=scad if body.include_scad else None,
                scad_length=len(scad), error=None, cost_zone="free",
                latency_ms=(time.perf_counter() - t0) * 1000,
            ))
        except Exception as exc:
            results.append(BatchResultItem(
                index=i, label=None, assembly_type=spec.assembly_type,
                scad_source=None, scad_length=0, error=str(exc),
                cost_zone="free", latency_ms=(time.perf_counter() - t0) * 1000,
            ))

    if body.seed_mubit:
        for r in results:
            if r.error is None and r.assembly_type:
                asyncio.create_task(remember_template_generation(
                    prompt=f"[programmatic] {r.assembly_type}",
                    assembly_type=r.assembly_type,
                    scad_length=r.scad_length,
                    model_used="programmatic",
                ))

    succeeded = sum(1 for r in results if r.error is None)
    return BatchTemplateResponse(
        total=len(specs),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        free_tier_count=len(specs),
        llm_tier_count=0,
        results=results,
        total_latency_ms=(time.perf_counter() - t_start) * 1000,
    )
