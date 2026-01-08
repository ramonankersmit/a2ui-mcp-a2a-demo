# A2A Restaurant Rater (deterministic)

Deterministic A2A agent that enriches restaurant lists with scores, rationales, and recommendations. No LLMs or external calls.

## Install (venv)

```bash
py -m venv .venv
.venv\Scripts\activate
py -m pip install -r demos/a2a_restaurant_rater/requirements.txt
```

## Run the server

Run from the repository root so the `demos` package is importable:

```bash
cd /path/to/a2ui-mcp-a2a-demo
py -m demos.a2a_restaurant_rater.server
```

Optional environment variables:
- `A2A_RATER_HOST` (default: `localhost`)
- `A2A_RATER_PORT` (default: `8002`)

Agent card endpoint:
- `http://localhost:8002/.well-known/agent-card.json`

## Run the test client

```bash
py demos/a2a_restaurant_rater/test_client.py
```

The client posts a JSON-RPC `sendMessage` request to `http://localhost:8002/` with a `rate_restaurants` payload and prints the response.
