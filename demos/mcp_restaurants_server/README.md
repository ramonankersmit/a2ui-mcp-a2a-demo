# MCP Restaurants Tool Server (local demo)

Local MCP tool server with deterministic restaurant data and fake latency for UI demos.

## Requirements
- Windows 10/11
- Python 3.9+
- MCP Python SDK (`mcp`)

## Install
From repo root (Windows Git Bash or CMD):

```bash
py -m pip install -r demos/mcp_restaurants_server/requirements.txt
```

## Run
Default host/port: `localhost:7001`

```bash
py -m demos.mcp_restaurants_server.server
```

Override host/port with environment variables:

```bash
set MCP_HOST=127.0.0.1
set MCP_PORT=7001
py -m demos.mcp_restaurants_server.server
```

## Transport / URL
This server exposes MCP over **SSE** at:

```
http://localhost:7001/sse
```

## Tools
- `search_restaurants(query: str, location: str) -> list[dict]`
- `get_availability(restaurant_id: str, date: str) -> list[str]`

## Example tool calls (Python)

```python
import asyncio
from mcp.client import ClientSession
from mcp.client.sse import sse_client


async def main() -> None:
    async with sse_client("http://localhost:7001/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            search = await session.call_tool(
                "search_restaurants",
                {"query": "sushi", "location": "Amsterdam"},
            )
            print("search_restaurants:", search.content)

            availability = await session.call_tool(
                "get_availability",
                {"restaurant_id": "r4", "date": "2025-02-14"},
            )
            print("get_availability:", availability.content)


if __name__ == "__main__":
    asyncio.run(main())
```

## Notes
- Data is fully local and deterministic.
- Each tool call adds fake latency (300–700ms) to make UI updates visible.
- No external API calls or secrets are required.
