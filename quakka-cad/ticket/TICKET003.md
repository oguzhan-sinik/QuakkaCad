# TICKET-003: Iterative 3D Design — Version Control, Voice Commands & Multi-Object Support

## Summary
Evolve the single-shot 3D generation flow into a fast, iterative design loop. The initial model is generated with Claude Opus (high quality), and subsequent edits are applied by a fast model (Claude Haiku, ~2s per change). Designers can make quick adjustments via voice commands during a meeting, manage multiple objects per session, and browse the full version history of each object.

## Goal
A meeting participant can create an initial 3D design, then refine it with near-instant voice-driven edits ("make it 10mm taller", "add a hole on the left side") — each change taking ~2 seconds — while maintaining full version history and the ability to work on multiple objects in one session.

## Background
Currently, every generation is a full Opus call (~15-30s) with no memory of prior output. This makes small tweaks expensive and slow. By splitting into a two-tier model strategy (Opus for creation, Haiku for edits) and feeding the current OpenSCAD code as context, we can achieve sub-3s iteration cycles for dimensional and simple geometric changes.

## Scope

### In scope

#### 1. Two-Tier Model Strategy
- **Initial generation**: Claude Opus via Pydantic Gateway — high-quality, parametric OpenSCAD code (~15-30s).
- **Iterative edits**: Claude Haiku via Pydantic Gateway — receives the current OpenSCAD code + the edit instruction, returns the modified code (~2s).
- The system auto-selects the model: Opus for "create new", Haiku for "edit existing".
- If Haiku produces a compilation error, auto-retry once with the error message appended. If it fails again, escalate to Opus.

#### 2. Version Control for 3D Objects
- Every generation or edit creates a new version, stored in an ordered list per object.
- Each version stores: version number, OpenSCAD code, timestamp, prompt/instruction that produced it, model used, compilation status.
- UI: version history panel showing a scrollable list of versions with one-click restore.
- "Undo" reverts to the previous version. "Redo" moves forward if available.
- Restoring an old version creates a new version (branch-from-history), preserving the full timeline.

#### 3. Voice Commands for Instant Edits
- At the start of a meeting, a popup/modal explains voice command capabilities and asks for opt-in.
- Voice commands are extracted from the live transcript (from TICKET-002) using keyword detection.
- Supported command patterns:
  - Dimensional changes: "make it [X]mm taller/wider/shorter/deeper"
  - Parameter edits: "change [parameter] to [value]"
  - Add/remove features: "add a hole on the top", "remove the fillet"
  - Color changes: "make the lid red"
  - Undo/redo: "undo that", "go back"
- Commands are detected, shown as a confirmation toast ("Changing height to 50mm..."), and executed via Haiku.
- A small indicator in the UI shows when voice command mode is active.

#### 4. Multi-Object Support
- A meeting can contain multiple named 3D objects (e.g., "Enclosure", "Lid", "Bracket").
- Object selector (tabs or dropdown) in the CAD panel to switch between objects.
- Each object has its own independent version history, code editor, and 3D preview.
- "New Object" button to create additional objects within the same meeting.
- Voice commands apply to the currently selected object.

## UI Changes

### CAD Panel Updates
```
┌─────────────────────────────────────────────────────┐
│  Objects: [ Enclosure ▾ ]  [+ New Object]           │
├────────────┬────────────────────────────────────────┤
│  Versions  │  [ OpenSCAD Code ]  [ 3D Preview ]    │
│            │                                        │
│  v5 ●      │  // Parametric enclosure               │
│  v4        │  box_width = 60;                       │
│  v3        │  box_height = 50;  // was 40           │
│  v2        │  ...                                   │
│  v1        │                                        │
│            │                                        │
│  [Undo]    │                                        │
│  [Redo]    │                                        │
├────────────┴────────────────────────────────────────┤
│  🎙 Voice commands active                           │
│  [prompt input: "make the walls thicker"    ] [Send]│
└─────────────────────────────────────────────────────┘
```

### Voice Command Opt-In Modal (meeting start)
```
┌──────────────────────────────────────┐
│  🎙 Enable Voice Commands?          │
│                                      │
│  You can make instant changes to     │
│  your 3D designs by speaking:        │
│                                      │
│  • "Make it 10mm taller"             │
│  • "Change wall thickness to 3mm"    │
│  • "Add a hole on the top"           │
│  • "Undo that"                       │
│                                      │
│  Commands are detected from your     │
│  live transcript automatically.      │
│                                      │
│  [ Enable ]          [ Skip ]        │
└──────────────────────────────────────┘
```

## User Flow

### Initial Creation
1. User types or speaks a description: "Create an electronics enclosure 60x40x30mm".
2. System routes to Opus, generates initial OpenSCAD code (~20s).
3. Code compiles via WASM, 3D preview appears. Version v1 is saved.

### Iterative Editing (text)
1. User types "make the walls 3mm thick" in the prompt input.
2. System sends current code + instruction to Haiku (~2s).
3. New code replaces the editor, preview updates. Version v2 is saved.

### Iterative Editing (voice)
1. User says during the meeting: "make the box 10mm taller".
2. Voice command detector picks it up from the transcript.
3. A toast appears: "Changing box height +10mm..." with a cancel button (3s window).
4. If not cancelled, Haiku edits the code. Version v3 is saved.

### Version Navigation
1. User clicks v1 in the version list.
2. Code and preview revert to v1's state.
3. A "Restore this version" button appears. Clicking it creates v6 (copy of v1).

### Multi-Object
1. User clicks "+ New Object", names it "Lid".
2. CAD panel switches to the new empty object.
3. User creates the lid design. Independent version history begins.
4. User switches back to "Enclosure" via the object selector — its state is preserved.

## Technical Design

### Two-Tier Model Routing (api/agents.py)
```python
# Edit prompt wraps current code + instruction for Haiku
EDIT_SYSTEM_PROMPT = """\
You are an OpenSCAD code editor. You receive existing OpenSCAD code and an edit instruction.
Apply the requested change precisely. Return the COMPLETE modified OpenSCAD code.
Do NOT explain changes — return ONLY the updated code.
Preserve all existing structure, comments, and parameters unless the edit requires changing them.
"""

async def run_edit(
    current_code: str,
    instruction: str,
    provider: str = "pydantic-fast",  # Haiku by default
    max_tokens: int = 8192,
) -> tuple[str, dict]:
    ...
```

### Version Storage (per object)
```python
class ObjectVersion(BaseModel):
    version: int
    code: str
    timestamp: datetime
    instruction: str          # prompt or voice command that produced this
    model_used: str           # "opus" or "haiku"
    compile_status: str       # "success", "error", "pending"
    compile_error: str | None

class DesignObject(BaseModel):
    id: UUID
    meeting_id: UUID
    name: str
    versions: list[ObjectVersion]
    current_version: int
```

### Voice Command Detection
- Runs on committed transcript lines from TICKET-002.
- Pattern matching + lightweight classification to distinguish commands from conversation.
- Debounce: ignore duplicate-sounding commands within 5 seconds.
- Confirmation toast with cancel window before executing.

### API Endpoints
- `POST /api/meetings/{id}/objects` — create a new object in a meeting
- `GET /api/meetings/{id}/objects` — list objects in a meeting
- `POST /api/meetings/{id}/objects/{obj_id}/generate` — initial Opus generation
- `POST /api/meetings/{id}/objects/{obj_id}/edit` — Haiku edit (sends current code + instruction)
- `GET /api/meetings/{id}/objects/{obj_id}/versions` — version history
- `POST /api/meetings/{id}/objects/{obj_id}/versions/{v}/restore` — restore a past version

## Acceptance Criteria

1. Initial generation uses Opus and produces a compilable parametric OpenSCAD model.
2. Editing an existing model via text prompt uses Haiku and returns updated code in <5 seconds.
3. Every generation/edit creates a new version entry with code, timestamp, instruction, and model used.
4. User can browse version history, click any version to preview it, and restore it.
5. Undo/redo navigates through version history correctly.
6. Voice commands are detected from the live transcript and produce edits via Haiku.
7. A confirmation toast appears before executing a voice command, with a cancel option.
8. Voice command opt-in modal appears at meeting start; commands are only active if opted in.
9. Multiple objects can be created in one meeting, each with independent state and version history.
10. Switching between objects preserves each object's code, preview, and version history.
11. If Haiku produces a compilation error, the system retries once with error context, then falls back to Opus.

## Risks / Open Questions
- **Voice command false positives**: conversational speech like "I think we should make it taller" vs. the actual command "make it taller". May need a trigger phrase ("hey quakka, make it taller") or rely on the confirmation toast as a safety net.
- **Haiku accuracy on complex edits**: simple dimensional changes are reliable, but structural edits ("add a gear mechanism") may exceed Haiku's capabilities. The Opus fallback handles this, but latency spikes from 2s to 20s.
- **Context window for edits**: large OpenSCAD files (500+ lines) plus instructions may approach Haiku's context limits. Consider sending only relevant parameter sections for simple dimensional changes.
- **Cost**: Haiku edits are very cheap (~$0.001/edit). Opus creations are ~$0.05-0.15 each. Voice commands could trigger many Haiku calls — monitor usage per meeting.
- **Version storage**: in-memory for MVP (consistent with TICKET-002). Persistence to database is a follow-up.

## Definition of Done
- Two-tier model routing works: Opus for creation, Haiku for edits, with automatic fallback.
- Version history UI is functional with browse, restore, undo, and redo.
- Voice commands trigger edits from the live transcript with confirmation UX.
- Multi-object support with independent state per object.
- Manual test with a 3-participant meeting: create 2 objects, make 5+ voice edits, navigate version history.
- Code reviewed and merged to `main`.
