# Plan: Integrate MuBit into LLM Generation Pipeline

## Context
MuBit provides persistent memory for AI agents — storing lessons from past generations and surfacing them as context before future LLM calls. No native Pydantic AI adapter exists, so we'll use the `mubit-sdk` directly alongside our existing Pydantic AI agents.

## Architecture

The integration wraps each agent call with a **remember → get_context → generate → record_outcome → reflect** loop:

```
[User prompt]
    → get_context() (fetch lessons from past generations)
    → inject lessons into prompt
    → Pydantic AI agent.run()
    → remember() (store the interaction)
    → record_outcome() (success/failure based on OpenSCAD compilation)
    → reflect() (extract reusable lessons periodically)
```

## Changes

### 1. Install `mubit-sdk` (api/requirements.txt or pyproject.toml)
- `pip install mubit-sdk`

### 2. Add env var to `api/.env`
- `MUBIT_API_KEY="mbt_<instance>_<key_id>_<secret>"`

### 3. Create `api/mubit_client.py` — thin wrapper
- Initialize `mubit.Client()` lazily (only when `MUBIT_API_KEY` is set)
- Helper functions:
  - `get_generation_context(agent_id, session_id)` → calls `client.get_context()` with token budget (~500 tokens), returns string to inject into prompt
  - `remember_generation(agent_id, session_id, prompt, code, model_used)` → stores the interaction as a fact
  - `record_generation_outcome(session_id, success, error_msg, signal)` → records compilation success/failure
  - `reflect_on_session(session_id)` → extracts lessons after a generation cycle
- If `MUBIT_API_KEY` is not set, all functions are no-ops (graceful degradation)

### 4. Modify `api/agents.py` — inject MuBit into the 3 runner functions

**`run_generate()`:**
- Before LLM call: fetch context via `get_generation_context("openscad-generator", session_id)`
- Prepend lessons to the user prompt: `f"LESSONS FROM PAST GENERATIONS:\n{context}\n\nUSER REQUEST:\n{prompt}"`
- After LLM call: `remember_generation(...)` with the prompt and generated code
- Add `session_id` parameter (defaults to a new UUID per call)

**`run_planner()`:**
- Before LLM call: fetch context for `"planner"` agent
- Append lessons to the existing prompt block
- After: remember the interaction

**`run_openscad_meeting()`:**
- Before LLM call: fetch context for `"openscad-meeting"` agent
- Append lessons to the prompt
- After: remember the interaction

### 5. Modify `api/routers/generate.py` — add outcome recording
- After the frontend compiles OpenSCAD (success/failure), call a new endpoint to record the outcome
- New endpoint: `POST /api/generate/outcome` — accepts `{ session_id, success, error }`, calls `record_generation_outcome()` + `reflect_on_session()`

### 6. Modify frontend `CadPanel.tsx` — report compilation outcomes
- After WASM compilation succeeds or fails, POST to `/api/generate/outcome` with the session_id (returned from the generate response) and success/error status
- This closes the feedback loop so MuBit learns from compilation results

## File Summary
| File | Action |
|------|--------|
| `api/mubit_client.py` | **New** — MuBit client wrapper |
| `api/agents.py` | **Edit** — inject context before LLM calls, remember after |
| `api/routers/generate.py` | **Edit** — add outcome endpoint, pass session_id in response |
| `quakka-cad/app/components/CadPanel.tsx` | **Edit** — POST compilation outcome to backend |
| `quakka-cad/next.config.ts` | **Edit** — add rewrite for `/api/generate/outcome` |
| `api/.env` | **Edit** — add `MUBIT_API_KEY` |
