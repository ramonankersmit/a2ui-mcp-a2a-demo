# RUN_NOTES (baseline A2UI demo)

## 1) Prerequisites check (Windows Git CMD)

Commands executed in this repo (current environment):

```bash
git --version
```
Output:
```
git version 2.43.0
```

```bash
node --version
```
Output:
```
v20.19.5
```

```bash
npm --version
```
Output:
```
npm warn Unknown env config "http-proxy". This will stop working in the next major version of npm.
11.4.2
```

```bash
py --version
```
Output:
```
bash: command not found: py
```

> Note: On Windows, `py --version` should print the Python Launcher version (e.g., `Python 3.11.x`). In this environment the `py` launcher is not available.

## 2) Baseline demo run (Lit shell + restaurant/contact agents)

Location:
```
cd samples/client/lit
```

Commands to run (Windows Git CMD):
```bash
npm install
npm run demo:all
```

Status: **Not executed in this environment.** The commands above are the intended baseline run steps, but I did not run them here.

What `demo:all` starts (from `samples/client/lit/package.json`):
- **Shell UI dev server**: `npm run serve:shell` (Lit shell) 
- **Restaurant agent**: `npm run serve:agent:restaurant`
- **Contact lookup agent**: `npm run serve:agent:contact_lookup`

Expected URLs / ports:
- UI: **http://localhost:5173/** (Lit dev server)
- Restaurant agent backend: **http://localhost:10002**
- Contact lookup agent backend: **http://localhost:10003**
- Agent cards: `/.well-known/agent-card.json` on each agent base URL

Streaming / task updates:
- The A2A servers are configured with `streaming=True`. Task updates are emitted via the A2A task stream (used by the SDK client). The restaurant agent executor sends interim updates and a final A2UI payload when the task completes.

Environment variables / keys:
- **GEMINI_API_KEY** is required unless `GOOGLE_GENAI_USE_VERTEXAI=TRUE` is set.
- Optional: **GOOGLE_GENAI_USE_VERTEXAI=TRUE**
- Optional model override: **LITELLM_MODEL** (defaults to `gemini/gemini-2.5-flash`).

Where this is indicated:
- `samples/agent/adk/restaurant_finder/.env.example`
- `samples/agent/adk/contact_lookup/.env.example`
- `samples/agent/adk/restaurant_finder/__main__.py` and `samples/agent/adk/contact_lookup/__main__.py`
- `samples/agent/adk/restaurant_finder/agent.py`

## 3) Hotspots / edit targets (restaurant finder agent)

Target path: `samples/agent/adk/restaurant_finder/`

### A) Where A2UI “surface” (UI schema) is built/sent
1. **`prompt_builder.py`**
   - Defines `A2UI_SCHEMA` and `get_ui_prompt(...)` which assembles the LLM instructions, schema, and example payloads that drive UI generation.
   - This is the source of truth for how the UI JSON is structured and validated.

2. **`a2ui_examples.py`**
   - Contains the **beginRendering** + **surfaceUpdate** templates used by the LLM to build the surface layout.
   - These templates are injected into prompts and used verbatim by the agent response.

3. **`agent_executor.py`**
   - Parses the final LLM output and turns the UI JSON into A2A `DataPart` messages via `create_a2ui_part(...)`.
   - This is where the UI payload is actually sent to the client.

### B) Where incremental updates / `dataModelUpdate` is emitted (streaming/SSE/JSONL)
1. **`a2ui_examples.py`**
   - Each example includes a `dataModelUpdate` message; this is the expected incremental update format.
   - The prompt instructs the LLM to populate `dataModelUpdate.contents` with restaurant data.

2. **`prompt_builder.py`**
   - The rules explicitly tell the LLM to populate `dataModelUpdate.contents`.
   - If we want to switch to multi-step JSONL/SSE streaming of updates, this prompt is the primary control point.

3. **`agent_executor.py` + `agent.py`**
   - `agent.py` streams intermediate updates via `yield {"is_task_complete": False, ...}`.
   - `agent_executor.py` forwards those updates to the A2A task stream via `TaskUpdater.update_status(...)`.

### C) Where user actions/events enter (button click / form submit)
1. **`agent_executor.py`**
   - In `execute(...)`, detects `DataPart` payloads with `userAction` and dispatches by `actionName`.
   - Handles `book_restaurant` and `submit_booking` actions, converting them into LLM queries.

2. **`a2ui_examples.py`**
   - Defines the action names and context payloads for the UI buttons (`book_restaurant`, `submit_booking`).
   - This is where new UI actions should be added if we expand the UX.

### D) Best place to implement orchestrator flow (MCP calls + A2A call)
1. **`agent_executor.py`**
   - Central request entry point that decides whether the message is a UI action or free-text.
   - Best place to intercept requests and route them through an orchestrator before calling `agent.stream(...)`.

2. **`agent.py`**
   - The LLM pipeline and schema validation live here; integrating MCP tool calls can happen before invoking the runner or by adding additional tools.
   - Useful if orchestration is LLM-driven rather than purely in the executor.

## 4) Baseline README (created)
- `README_DEMO.md` at repo root contains **baseline** demo run instructions for Windows Git CMD.

## 5) .gitignore check
- Added `build/` and `*.env` entries to ensure build artifacts and environment files are ignored.
