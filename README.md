# Quakka CAD

AI-powered voice-first CAD collaboration platform. Engineering teams join a voice conference, discuss designs naturally, and AI agents extract structured plans and generate parametric 3D models in real time.

## How It Works

```
Voice Conference (WebRTC)
    |
    v
Real-time Transcription (ElevenLabs Scribe)
    |
    v
Planner Agent extracts objectives, variables, decisions, missing info
    |
    v
CAD Agent generates parametric OpenSCAD --> headless compile --> STL
    |
    v
3D Preview (Three.js) + FEA Analysis + Technical Drawings
```

## Features

- **Voice-first design** -- speak naturally, AI extracts structured design blocks
- **Real-time collaboration** -- WebRTC peer-to-peer audio with live transcription
- **Parametric CAD generation** -- OpenSCAD from natural language via multi-provider LLMs
- **Template library** -- 21 pre-built mechanical assemblies (gears, springs, linkages, rocket body tubes, stack assemblies, etc.)
- **Auto-compilation** -- headless OpenSCAD with automatic error fixing
- **FEA analysis** -- stress testing with material library (PLA, ABS, PETG, Nylon, Aluminum, Steel)
- **Technical drawings** -- LLM-generated 2D engineering documentation
- **Gesture controls** -- optional MediaPipe hand tracking for 3D view manipulation
- **Voice commands** -- hands-free control via fuzzy-matched spoken commands
- **Persistent memory** -- MuBit integration learns from past designs

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS 4 |
| 3D Rendering | Three.js |
| Voice | WebRTC, ElevenLabs Scribe (VAD-based transcription) |
| Gestures | MediaPipe Vision |
| Backend | FastAPI, Python 3.10+ |
| LLM Agents | Pydantic AI (Groq / Cerebras / Anthropic) |
| CAD Engine | OpenSCAD (headless compilation) |
| FEA | gmsh + scipy |
| Memory | MuBit SDK |
| Observability | Logfire |

## Project Structure

```
quakka-cad/              Next.js frontend
  app/
    [conferenceId]/      Main conference room (voice + CAD + planning)
    components/          ConferenceRoom, CadPanel, TranscriptPanel, PlanSidebar
    lib/                 useConference, useScribe, useVoiceCommands
    hooks/               useGestureControls
    api/                 Route handlers (plan, model, refine, fea, drawing, template)

api/                     FastAPI backend
  agents.py              LLM agents (planner, generator, editor, fixer, refiner, FEA)
  templates/
    models.py            Pydantic specs for all 21 assembly types
    agent.py             Template classification agent + system prompt
    render.py            Render pipeline (prompt -> spec -> compose -> .scad)
    assemblies/          Composers for each template type
    atomic/              Reusable OpenSCAD modules (.scad)
  openscad_compiler.py   Headless OpenSCAD compilation
  fea_solver.py          Mesh generation + FEM stress analysis
  mubit_client.py        MuBit persistent memory integration
  storage.py             In-memory meeting/transcript/model store
  routers/               FastAPI route modules
```

## Getting Started

### Prerequisites

- Node.js 20+
- Python 3.10+
- [OpenSCAD](https://openscad.org/) installed and on PATH
- [uv](https://docs.astral.sh/uv/) (Python package manager)

### Environment Variables

Create `api/.env`:

```env
# LLM providers (at least one required)
PYDANTIC_AI_GATEWAY_API_KEY=...   # Groq + Anthropic via Pydantic Gateway
CEREBRAS_API_KEY=...              # Cerebras

# Voice transcription
ELEVENLABS_API_KEY=...

# Optional
MUBIT_API_KEY=...                 # Persistent agent memory
MUBIT_PROJECT_ID=...
FAL_KEY=...                       # Image generation for drawings
```

### Run

```bash
# Backend
cd api
uv sync
uv run python main.py
# -> http://localhost:8000

# Frontend (separate terminal)
cd quakka-cad
npm install
npm run dev
# -> http://localhost:3000
```

Open http://localhost:3000, create a conference, and start talking.

## Template Library

21 parametric assembly types, each with full LLM-guided parameter selection:

| Category | Templates |
|---|---|
| Rocketry | finned_rocket_body, body_tube, bulkhead, mounting_plate |
| Gears | gear_train, planetary_gear, worm_gear, rack_and_pinion, differential_gear |
| Transmission | belt_pulley, shaft_coupling, universal_joint, lead_screw, cam_follower |
| Mechanisms | four_bar_linkage, helical_spring |
| Structural | flanged_tube, bushing_assembly, hex_standoff |
| Composite | stack_assembly (multi-part assemblies with rotation + positioning) |

## API Endpoints

| Endpoint | Description |
|---|---|
| `POST /api/conference` | Create a conference |
| `WS /ws/{conferenceId}` | Join conference (signaling + transcripts) |
| `POST /api/meetings` | Create a meeting |
| `POST /api/meetings/{id}/agent/plan` | Run planner (SSE stream) |
| `POST /api/meetings/{id}/agent/model` | Generate CAD model |
| `POST /api/meetings/{id}/agent/refine` | Refine existing model |
| `POST /api/meetings/{id}/agent/fea` | Run FEA analysis |
| `POST /api/meetings/{id}/agent/drawing` | Generate technical drawing |
| `POST /generate` | Free-form OpenSCAD generation |
| `POST /api/batch/template` | Batch template generation |

## License

Proprietary.
