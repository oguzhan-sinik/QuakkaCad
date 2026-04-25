import os
import time
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import logfire
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(ENV_PATH)

logfire.configure()
logfire.instrument_pydantic_ai()

# --- Load system prompt ---
PROMPT_PATH = Path(__file__).parent / "prompt.md"
SYSTEM_PROMPT = PROMPT_PATH.read_text()

# --- Pydantic AI Agents per provider ---
mercury_model = OpenAIChatModel(
    "mercury-2",
    provider=OpenAIProvider(
        base_url="https://api.inceptionlabs.ai/v1",
        api_key=os.getenv("INCEPTION_API_KEY", ""),
    ),
)

cerebras_model = OpenAIChatModel(
    "zai-glm-4.7",
    provider=OpenAIProvider(
        base_url="https://api.cerebras.ai/v1",
        api_key=os.getenv("CEREBRAS_API_KEY", ""),
    ),
)

PROVIDER_CONFIG = {
    "mercury": {"model": mercury_model, "label": "Inception Mercury 2", "key_env": "INCEPTION_API_KEY"},
    "cerebras": {"model": cerebras_model, "label": "Cerebras", "key_env": "CEREBRAS_API_KEY"},
    "pydantic": {"model": "openai:gpt-4o", "label": "Pydantic (GPT-4o)", "key_env": "LOGFIRE_TOKEN"},
}

agents: dict[str, Agent] = {}
for name, cfg in PROVIDER_CONFIG.items():
    # Skip providers without API keys at startup (lazy-init on first request)
    if not os.getenv(cfg["key_env"], ""):
        continue
    agents[name] = Agent(
        cfg["model"],
        system_prompt=SYSTEM_PROMPT,
        output_type=str,
    )


# --- Pydantic request/response models ---
class ProviderEnum(str, Enum):
    mercury = "mercury"
    cerebras = "cerebras"
    pydantic = "pydantic"


class GenerateRequest(BaseModel):
    prompt: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Natural language description of the 3D object to generate.",
        examples=["A rocket fin can assembly with 4 fins"],
    )
    provider: ProviderEnum = Field(
        default=ProviderEnum.mercury,
        description="LLM provider to use.",
    )
    temperature: float = Field(
        default=0.75,
        ge=0.0,
        le=2.0,
        description="Sampling temperature.",
    )
    max_tokens: int = Field(
        default=8192,
        ge=256,
        le=16384,
        description="Maximum tokens in the response.",
    )


class GenerateResponse(BaseModel):
    openscad_code: str = Field(..., description="The generated OpenSCAD source code.")
    provider: str = Field(..., description="Provider that was used.")
    model_used: str = Field(..., description="Model ID that produced the code.")
    latency_ms: float = Field(..., description="End-to-end LLM call duration in ms.")
    usage: dict = Field(default_factory=dict, description="Token usage stats.")
    tokens_per_second: float | None = Field(default=None, description="Output tokens per second.")


def strip_markdown_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)
    return text


# --- App ---
app = FastAPI(title="Unicorn Mafia - 3D Generator API", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "providers": list(PROVIDER_CONFIG.keys())}


@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest):
    provider_name = req.provider.value
    cfg = PROVIDER_CONFIG[provider_name]

    api_key = os.getenv(cfg["key_env"], "")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail=f"{cfg['key_env']} is not set. Add it to backend/.env",
        )

    # Lazy-init agent if it wasn't created at startup
    if provider_name not in agents:
        agents[provider_name] = Agent(
            cfg["model"],
            system_prompt=SYSTEM_PROMPT,
            output_type=str,
        )
    agent = agents[provider_name]

    t0 = time.perf_counter()
    try:
        result = await agent.run(
            req.prompt,
            model_settings={
                "temperature": req.temperature,
                "max_tokens": req.max_tokens,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"{cfg['label']} error: {e}")
    latency_ms = (time.perf_counter() - t0) * 1000

    content = strip_markdown_fences(result.output)

    usage_data = result.usage()
    usage = {
        "prompt_tokens": usage_data.input_tokens,
        "completion_tokens": usage_data.output_tokens,
        "total_tokens": usage_data.total_tokens(),
    }

    tokens_per_second = None
    if usage_data.output_tokens and latency_ms > 0:
        tokens_per_second = round(usage_data.output_tokens / (latency_ms / 1000), 1)

    return GenerateResponse(
        openscad_code=content.strip(),
        provider=cfg["label"],
        model_used=str(cfg["model"]),
        latency_ms=round(latency_ms, 1),
        usage=usage,
        tokens_per_second=tokens_per_second,
    )


# --- Viewer page ---
VIEWER_HTML = Path(__file__).parent / "viewer.html"


@app.get("/", response_class=HTMLResponse)
def viewer():
    return VIEWER_HTML.read_text()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
