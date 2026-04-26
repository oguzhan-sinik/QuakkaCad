# TICKET-003: Composable Template Pipeline — Prompt to 3D Mechanical Parts in <8s

## Summary
Add a fast, template-based 3D generation path to QuakkaCAD. Instead of asking an LLM to write raw geometry code (which only works with frontier models), the LLM classifies a prompt into a known assembly type and fills in validated parameters. Pre-built OpenSCAD atomic templates handle all geometry. The pipeline runs on Cerebras (Qwen 3 235B) via Pydantic AI and targets <8s end-to-end from prompt to rendered STL.

## Goal
A meeting participant types or speaks "90mm motor tube, 200mm long, 4 swept fins, 2 centering rings" and sees a correct, compilable 3D model in the viewer within 8 seconds — without requiring a frontier model.

## Background
The current generation flow (`run_openscad_meeting` / `run_cadquery_meeting` in `api/agents.py`) asks the LLM to write full OpenSCAD or CadQuery code from scratch. This works well with Claude Sonnet/Opus but fails on fast models (Groq, Cerebras) because spatial reasoning for mechanical parts — concentric axes, fin spacing, gear meshing — exceeds their capabilities. The template pipeline sidesteps this by reducing the LLM's job to classification + parameter extraction, which fast models do reliably.

This sits alongside the existing freeform generation (OpenSCAD and CadQuery buttons remain), giving users a third "fast template" path.

## Scope

### In scope
- Atomic OpenSCAD template library (parametric `.scad` modules)
- Python assembly composition functions that emit complete `.scad` source from validated specs
- Pydantic models with geometric validators for each assembly type
- Pydantic AI agent on Cerebras (Qwen 3 235B Instruct) with structured output
- Render pipeline: spec -> composition -> OpenSCAD compile -> STL
- Integration into the existing QuakkaCAD meeting flow (new endpoint + UI button)
- Voice command trigger: "quick generate [description]"
- 5 demo prompts as integration tests

### Out of scope
- Curved/lofted surfaces beyond what `hull()` provides
- Internal threading, bearings, or rolling-element mechanisms
- Material/color/render styling (templates use default colors)
- Replacing the existing freeform OpenSCAD or CadQuery generation paths
- Database persistence (in-memory per meeting, consistent with current architecture)

## Architecture

```
User prompt (text or voice)
   |
   v
+-----------------------------------------------+
| Pydantic AI Agent                             |
|   model: cerebras:qwen-3-235b-instruct        |
|   output_type: AssemblySpec (discriminated)    |
|   retries: 1                                  |
|   system_prompt: assembly catalog + few-shot   |
+-----------------------------------------------+
   |
   v  (validated Pydantic model)
+-----------------------------------------------+
| Assembly dispatcher                           |
|   maps assembly_id -> composition function    |
|   composition fn calls atomic .scad templates |
+-----------------------------------------------+
   |
   v  (generated .scad text)
+-----------------------------------------------+
| OpenSCAD CLI (existing openscad_compiler.py)  |
|   openscad -o out.stl assembly.scad           |
|   timeout: 5s, $fn=32                         |
+-----------------------------------------------+
   |
   v
  STL bytes -> 3D viewer (existing CadPanel)
```

### Integration with existing codebase

```
api/
  agents.py              # Add Cerebras provider + template agent
  schemas.py             # Add AssemblySpec union type
  openscad_compiler.py   # Reuse existing compile_openscad()
  routers/
    meetings.py          # Add POST /meetings/{id}/agent/template endpoint
  templates/
    atomic/              # New: .scad module files
      tube.scad
      ring.scad
      slotted_ring.scad
      trapezoidal_fin.scad
      spur_gear.scad
      flange.scad
    assemblies/           # New: Python composition functions
      __init__.py
      finned_rocket_body.py
      gear_train.py
      bushing_assembly.py
      flanged_tube.py
    models.py             # New: Pydantic specs + validators
    agent.py              # New: Template pipeline agent
    render.py             # New: spec -> scad -> STL pipeline

quakka-cad/
  app/
    [conferenceId]/page.tsx        # Add handleRunTemplate callback + voice command
    components/CadPanel.tsx        # Add "Quick Gen" button in toolbar
    components/ConferenceRoom.tsx   # Pass template props through
    api/meetings/[meetingId]/agent/template/route.ts  # New: proxy route
```

## Technical Design

### 1. Atomic SCAD Templates (`api/templates/atomic/`)

Each is a standalone `.scad` file exporting a single `module`. All centered on origin, axis = Z, produce manifold geometry.

| Template | Module signature | Notes |
|----------|-----------------|-------|
| `tube.scad` | `module tube(outer_d, wall_thickness, length)` | Hollow cylinder |
| `ring.scad` | `module ring(inner_d, radial_thickness, width)` | Centering ring |
| `slotted_ring.scad` | `module slotted_ring(inner_d, radial_thickness, width, slot_count, slot_width, slot_depth)` | Radial slots for fin pass-through |
| `trapezoidal_fin.scad` | `module trapezoidal_fin(root_chord, tip_chord, height, sweep, thickness)` | Root edge on Y axis, sweeps in +X |
| `spur_gear.scad` | `module spur_gear(teeth, module_val, thickness, bore_d)` | Involute gear (BOSL2 or known-good) |
| `flange.scad` | `module flange(outer_d, inner_d, thickness, bolt_count, bolt_circle_d, bolt_hole_d)` | Bolt pattern on circle |

Quality bar: each module renders standalone via `openscad -o test.stl atomic/X.scad` with a test wrapper.

### 2. Assembly Composition Functions (`api/templates/assemblies/`)

Python functions that take a validated Pydantic spec and return a complete `.scad` source string. They import atomic templates via `use <../atomic/X.scad>` and compose with `union()`, `difference()`, `translate()`, `rotate()`.

| Assembly | Spec model | Composition logic |
|----------|-----------|-------------------|
| `finned_rocket_body` | `FinnedRocketBodySpec` | tube + N rings (or slotted_rings if fins pass through) + M fins radially distributed |
| `gear_train` | `GearTrainSpec` | N spur gears with computed center distances from module + tooth counts |
| `bushing_assembly` | `BushingAssemblySpec` | Concentric tube + ring + optional flange |
| `flanged_tube` | `FlangedTubeSpec` | Tube + flange on one or both ends |

### 3. Pydantic Models (`api/templates/models.py`)

```python
from typing import Literal, Union, Annotated
from pydantic import BaseModel, Field, model_validator

class FinnedRocketBodySpec(BaseModel):
    assembly_id: Literal["finned_rocket_body"]
    reasoning: str = Field(description="Brief reasoning for parameter choices")
    tube_outer_d: float = Field(gt=10, lt=500, description="Tube outer diameter in mm")
    tube_wall: float = Field(gt=0.5, lt=20, description="Tube wall thickness in mm")
    tube_length: float = Field(gt=20, lt=2000, description="Tube length in mm")
    ring_count: int = Field(ge=0, le=4)
    ring_width: float = Field(gt=0, lt=100, description="Ring axial width in mm")
    ring_radial_thickness: float = Field(gt=0, lt=50)
    ring_spacing: float | None = None
    fin_count: int = Field(ge=0, le=8)
    fin_root_chord: float = Field(gt=0)
    fin_tip_chord: float = Field(ge=0)
    fin_height: float = Field(gt=0)
    fin_sweep: float = Field(ge=0)
    fin_thickness: float = Field(gt=0.5, lt=20)
    fins_through_rings: bool = True

    @model_validator(mode="after")
    def check_fits(self):
        if self.ring_count >= 2 and self.ring_spacing:
            if self.ring_spacing + 2 * self.ring_width > self.tube_length:
                raise ValueError(
                    "ring_spacing + ring widths exceed tube_length; "
                    "reduce ring_spacing or increase tube_length"
                )
        if self.fin_root_chord > self.tube_length:
            raise ValueError("fin_root_chord cannot exceed tube_length")
        return self

class GearTrainSpec(BaseModel):
    assembly_id: Literal["gear_train"]
    reasoning: str
    gear_count: int = Field(ge=2, le=6)
    teeth: list[int] = Field(min_length=2, max_length=6, description="Tooth count per gear")
    module_val: float = Field(gt=0.5, lt=10, description="Gear module (mm)")
    thickness: float = Field(gt=1, lt=50)
    bore_d: float = Field(gt=0, lt=50)

    @model_validator(mode="after")
    def check_teeth_count(self):
        if len(self.teeth) != self.gear_count:
            raise ValueError(f"teeth list length ({len(self.teeth)}) must match gear_count ({self.gear_count})")
        return self

class BushingAssemblySpec(BaseModel):
    assembly_id: Literal["bushing_assembly"]
    reasoning: str
    bore_d: float = Field(gt=1, lt=200)
    outer_d: float = Field(gt=2, lt=300)
    length: float = Field(gt=5, lt=500)
    flange: bool = False
    flange_outer_d: float | None = None
    flange_thickness: float | None = None

class FlangedTubeSpec(BaseModel):
    assembly_id: Literal["flanged_tube"]
    reasoning: str
    tube_outer_d: float = Field(gt=5, lt=500)
    tube_inner_d: float = Field(gt=1, lt=500)
    tube_length: float = Field(gt=10, lt=2000)
    flange_outer_d: float = Field(gt=5, lt=600)
    flange_thickness: float = Field(gt=1, lt=50)
    bolt_count: int = Field(ge=3, le=24)
    bolt_circle_d: float = Field(gt=5, lt=500)
    bolt_hole_d: float = Field(gt=1, lt=30)
    flange_both_ends: bool = False

    @model_validator(mode="after")
    def check_diameters(self):
        if self.tube_inner_d >= self.tube_outer_d:
            raise ValueError("tube_inner_d must be less than tube_outer_d")
        if self.flange_outer_d < self.tube_outer_d:
            raise ValueError("flange_outer_d must be >= tube_outer_d")
        return self

AssemblySpec = Annotated[
    Union[FinnedRocketBodySpec, GearTrainSpec, BushingAssemblySpec, FlangedTubeSpec],
    Field(discriminator="assembly_id"),
]
```

### 4. Cerebras Provider Config (`api/agents.py`)

```python
PROVIDER_CONFIG["cerebras"] = {
    "model": "openai:qwen-3-235b-instruct",
    "model_name": "qwen-3-235b-instruct",
    "label": "Cerebras (Qwen 3 235B Instruct)",
    "key_env": "CEREBRAS_API_KEY",
    "base_url": "https://api.cerebras.ai/v1",
}
```

Add `CEREBRAS_API_KEY` to `api/.env`.

### 5. Template Agent (`api/templates/agent.py`)

```python
TEMPLATE_SYSTEM_PROMPT = """
You are a mechanical parts classifier. Given a natural language description,
output a structured specification for one of these assembly types:

- finned_rocket_body: Rocket motor tubes with centering rings and fins
- gear_train: Multiple meshing spur gears
- bushing_assembly: Cylindrical bushings/bearings with optional flange
- flanged_tube: Tubes with bolt-pattern flanges

ALL dimensions are in millimeters. If the user omits a dimension, use sensible
engineering defaults. The 'reasoning' field should briefly explain your choices.

[few-shot examples per type]
"""
```

### 6. Render Pipeline (`api/templates/render.py`)

```python
async def render_template(spec: AssemblySpec) -> tuple[bytes, str]:
    """spec -> .scad composition -> OpenSCAD compile -> STL bytes.

    Returns (stl_bytes, scad_source).
    """
    # Dispatch to composition function
    scad_source = ASSEMBLY_DISPATCHERS[spec.assembly_id](spec)

    # Write to temp file, compile with existing openscad_compiler
    ok, stderr = await compile_openscad(scad_source, timeout=5.0)
    if not ok:
        raise RuntimeError(f"OpenSCAD compile failed: {stderr}")

    # Re-compile to get STL (current compile_openscad validates only)
    # Need to add STL export mode
    stl_bytes = await compile_openscad_to_stl(scad_source, timeout=5.0)
    return stl_bytes, scad_source
```

### 7. API Endpoint (`api/routers/meetings.py`)

```python
@router.post("/meetings/{meeting_id}/agent/template", tags=["agents"])
async def trigger_template_generation(meeting_id: UUID, prompt: str = Body(...)):
    """Fast template-based generation via Cerebras. Target: <8s e2e."""
    ...
```

### 8. Frontend Integration

- New orange "Quick Gen" button in CadPanel toolbar (next to CadQuery button)
- Voice command trigger: "quick generate [description]" or "template [description]"
- Result renders as STL in the existing 3D preview (same as CadQuery path)
- OpenSCAD source visible in code tab

## Demo Prompts

| # | Prompt | Expected assembly |
|---|--------|-------------------|
| 1 | "ball bushing with 8mm bore, 15mm OD, 24mm long" | `bushing_assembly` |
| 2 | "A central motor tube 90mm OD, 3mm wall, 200mm long. Two centering rings 80mm apart, 15mm wide, 4mm thick. 4 swept fins 90 deg apart through ring slots. Root 110mm, tip 50mm, sweep 60mm, height 110mm, 3mm thick." | `finned_rocket_body` |
| 3 | "a 3-stage gear train, module 1.5, 20-40-60 teeth, 5mm thick" | `gear_train` |
| 4 | "flanged tube, 50mm OD, 30mm ID, 100mm long, M5 bolt holes, 6 bolts" | `flanged_tube` |
| 5 | "rocket body 60mm OD, 1m long, 4 fins, no rings" | `finned_rocket_body` |

## Acceptance Criteria

1. Prompt-to-STL pipeline runs end-to-end in <8s p95 on the 5 demo prompts
2. At least 6 atomic templates and 4 assembly templates compile and render cleanly
3. Pydantic validators reject geometrically impossible inputs (inner > outer, fins > tube length) before OpenSCAD runs
4. Validation failures auto-retry once via Pydantic AI's retry loop with actionable error messages
5. All 5 demo prompts produce manifold STL output that renders in the QuakkaCAD 3D viewer
6. The template path integrates into the meeting flow: appears in model iteration history, works with version navigation
7. Voice command "quick generate [description]" triggers the template pipeline
8. Existing OpenSCAD and CadQuery generation paths are unaffected

## Risks / Open Questions

| Risk | Mitigation |
|------|-----------|
| Cerebras structured output unreliable on Qwen 3 | `reasoning: str` field before `assembly_id` forces brief CoT before classification |
| OpenSCAD render >5s for complex gears | Pre-set `$fn=32`, use `convexity` hints, timeout at 5s |
| Pydantic AI lacks native Cerebras provider | Use `OpenAIProvider` with Cerebras OpenAI-compatible base URL |
| Fin slot dimensions mismatch -> non-manifold | Compute `slot_width = fin_thickness + 0.2mm` clearance in composition fn, not from LLM |
| Cerebras downtime during demo | Pre-cache the 5 demo prompt outputs; serve from cache on exact match |
| BOSL2 not available on system OpenSCAD | Bundle a self-contained involute gear module instead of depending on BOSL2 |

## Definition of Done

- All 5 demo prompts pass end-to-end in integration tests
- p95 latency <8s measured across 10 runs of each demo prompt
- "Quick Gen" button and voice command work in a live meeting session
- Template iterations appear in CadPanel version history alongside freeform generations
- Manual test: 2 participants in a meeting, one uses template generation, other sees the model update
- Code reviewed and merged to `main`
