from __future__ import annotations

from enum import Enum

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agents import run_generate

router = APIRouter(tags=["generate"])


class ProviderEnum(str, Enum):
    pydantic = "pydantic"


class GenerateRequest(BaseModel):
    prompt: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Natural language description of the 3D object to generate.",
        examples=["A rocket fin can assembly with 4 fins"],
    )
    provider: ProviderEnum = Field(default=ProviderEnum.pydantic, description="LLM provider to use.")
    temperature: float = Field(default=0.75, ge=0.0, le=2.0, description="Sampling temperature.")
    max_tokens: int = Field(default=8192, ge=256, le=16384, description="Maximum tokens in the response.")


class GenerateResponse(BaseModel):
    openscad_code: str = Field(..., description="The generated OpenSCAD source code.")
    provider: str = Field(..., description="Provider label that was used.")
    model_used: str = Field(..., description="Model ID that produced the code.")
    latency_ms: float = Field(..., description="End-to-end LLM call duration in ms.")
    usage: dict = Field(default_factory=dict, description="Token usage stats.")
    tokens_per_second: float | None = Field(default=None, description="Output tokens per second.")


@router.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest):
    try:
        content, meta = await run_generate(
            prompt=req.prompt,
            provider=req.provider.value,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    return GenerateResponse(
        openscad_code=content,
        provider=meta["provider"],
        model_used=meta["model_name"],
        latency_ms=meta["latency_ms"],
        usage=meta["usage"],
        tokens_per_second=meta["tokens_per_second"],
    )
