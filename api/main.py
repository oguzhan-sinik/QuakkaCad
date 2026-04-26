from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import logfire

logging.basicConfig(level=logging.INFO)
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(Path(__file__).parent / ".env")

from agents import PROVIDER_CONFIG  # noqa: E402
from mubit_client import seed_template_library
from routers.conference import router as conference_router
from routers.generate import router as generate_router
from routers.meetings import router as meetings_router

logfire.configure(service_name="quakkacad-api")

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Seed MuBit template library in background — non-blocking, no-op if key absent
    asyncio.create_task(_init_mubit())
    yield


async def _init_mubit() -> None:
    try:
        await seed_template_library()
    except Exception as e:
        logger.warning("MuBit template seeding failed at startup: %s", e)


app = FastAPI(
    title="QuakkaCad API",
    description=(
        "Unified backend: stateless OpenSCAD generation, "
        "meeting-based CAD planning, conference BFF, and WebRTC signaling."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logfire.instrument_fastapi(app)

app.include_router(generate_router)
app.include_router(meetings_router)
app.include_router(conference_router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "providers": list(PROVIDER_CONFIG.keys())}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
