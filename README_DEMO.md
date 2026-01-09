# A2UI demo run instructions (Windows Git CMD)

These instructions cover the baseline A2UI demo plus the deterministic MCP + A2A demo mode.

## Prerequisites
- Git
- Node.js + npm
- Python 3.9+
- [UV](https://docs.astral.sh/uv/) (for `uv run` in the agents)
- A Gemini API key (or Vertex AI configured via env vars) for the normal LLM flow

## 1) Install client dependencies
```bash
cd samples/client/lit
npm install
```

## 2) Configure agent environment variables (LLM flow)
For each agent, create `.env` from the template and set your API key:

```bash
cd ../../agent/adk/restaurant_finder
cp .env.example .env
# Edit .env and set GEMINI_API_KEY

cd ../contact_lookup
cp .env.example .env
# Edit .env and set GEMINI_API_KEY
```

Optional env vars:
- `GOOGLE_GENAI_USE_VERTEXAI=TRUE` (skip GEMINI_API_KEY check)
- `LITELLM_MODEL=gemini/gemini-2.5-flash` (or another LiteLLM model)
- `MCP_SSE_URL` (default: `http://127.0.0.1:7001/sse`)
- `A2A_RATER_URL` (default: `http://localhost:8002/`)

## 3) Run the baseline demo (all services)
From `samples/client/lit`:

```bash
npm run demo:all
```

This command runs:
- Lit shell dev server
- Restaurant agent (A2A server)
- Contact lookup agent (A2A server)

## 4) Open the UI
- http://localhost:5173/

Use the **"Demo MCP+A2A"** button in the Restaurant Finder screen to trigger the deterministic demo pipeline.

## 5) MCP restaurants tool server (required for demo mode)
This repository includes a local MCP tool server for deterministic restaurant data.

```bash
py -m pip install -r demos/mcp_restaurants_server/requirements.txt
py -m demos.mcp_restaurants_server.server
```

Default endpoint:
- http://localhost:7001/sse (matches the default `MCP_SSE_URL`)

Optional env vars:
- `MCP_HOST` (default: `localhost`)
- `MCP_PORT` (default: `7001`)

## 6) A2A restaurant rater (required for demo mode)
Deterministic A2A agent (no LLMs or external calls) that enriches restaurant lists with scores.

```bash
cd /path/to/a2ui-mcp-a2a-demo
py -m pip install -r demos/a2a_restaurant_rater/requirements.txt
py -m demos.a2a_restaurant_rater.server
```

Default endpoint:
- http://localhost:8002
- Agent card: http://localhost:8002/.well-known/agent-card.json

Optional env vars:
- `A2A_RATER_HOST` (default: `localhost`)
- `A2A_RATER_PORT` (default: `8002`)
- `A2A_RATER_URL` (default: `http://localhost:8002/`)

## Ports / endpoints
- Restaurant agent: http://localhost:10002
- Contact lookup agent: http://localhost:10003
- Agent cards: `/.well-known/agent-card.json` on each agent base URL
- MCP restaurant tools (SSE): http://localhost:7001/sse (local demo) or `MCP_SSE_URL` (default `http://127.0.0.1:7001/sse`)
- A2A restaurant rater: http://localhost:8002
