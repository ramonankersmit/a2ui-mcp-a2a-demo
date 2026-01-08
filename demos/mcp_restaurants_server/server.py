import asyncio
import hashlib
import logging
import os
import random
from typing import Dict, List

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("mcp_restaurants_server")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

mcp = FastMCP("restaurant-tools")

RESTAURANTS: List[Dict[str, object]] = [
    {
        "id": "r1",
        "name": "Canal Bistro",
        "cuisine": "French",
        "rating": 4.7,
        "price_level": 3,
        "distance_km": 1.2,
    },
    {
        "id": "r2",
        "name": "Noord Pizza Lab",
        "cuisine": "Italian",
        "rating": 4.5,
        "price_level": 2,
        "distance_km": 2.4,
    },
    {
        "id": "r3",
        "name": "Spice Market",
        "cuisine": "Thai",
        "rating": 4.6,
        "price_level": 2,
        "distance_km": 3.1,
    },
    {
        "id": "r4",
        "name": "Harbor Sushi",
        "cuisine": "Japanese",
        "rating": 4.8,
        "price_level": 4,
        "distance_km": 0.8,
    },
    {
        "id": "r5",
        "name": "Market Street Grill",
        "cuisine": "American",
        "rating": 4.3,
        "price_level": 2,
        "distance_km": 1.7,
    },
    {
        "id": "r6",
        "name": "Green Garden",
        "cuisine": "Vegetarian",
        "rating": 4.4,
        "price_level": 2,
        "distance_km": 2.9,
    },
    {
        "id": "r7",
        "name": "Mesa Roja",
        "cuisine": "Mexican",
        "rating": 4.2,
        "price_level": 1,
        "distance_km": 3.8,
    },
    {
        "id": "r8",
        "name": "Saffron Lounge",
        "cuisine": "Indian",
        "rating": 4.6,
        "price_level": 3,
        "distance_km": 2.1,
    },
]


async def _simulate_latency() -> None:
    await asyncio.sleep(random.uniform(0.3, 0.7))


def _deterministic_slots(restaurant_id: str, date: str) -> List[str]:
    base_slots = [
        "17:30",
        "18:00",
        "18:30",
        "19:00",
        "19:30",
        "20:00",
        "20:30",
        "21:00",
    ]
    seed_input = f"{restaurant_id}:{date}".encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(seed_input).digest()[:4], "big")
    start_index = seed % len(base_slots)
    slots = [
        base_slots[start_index % len(base_slots)],
        base_slots[(start_index + 1) % len(base_slots)],
        base_slots[(start_index + 2) % len(base_slots)],
    ]
    return sorted(set(slots))


@mcp.tool()
async def search_restaurants(query: str, location: str) -> List[Dict[str, object]]:
    logger.info("search_restaurants(query=%s, location=%s)", query, location)
    await _simulate_latency()
    normalized_query = query.strip().lower()
    matches = [
        restaurant
        for restaurant in RESTAURANTS
        if not normalized_query
        or normalized_query in restaurant["name"].lower()
        or normalized_query in restaurant["cuisine"].lower()
    ]
    matches.sort(key=lambda restaurant: (-restaurant["rating"], restaurant["distance_km"]))
    return matches


@mcp.tool()
async def get_availability(restaurant_id: str, date: str) -> List[str]:
    logger.info("get_availability(restaurant_id=%s, date=%s)", restaurant_id, date)
    await _simulate_latency()
    return _deterministic_slots(restaurant_id, date)


def main() -> None:
    host = os.getenv("MCP_HOST", "localhost")
    port = int(os.getenv("MCP_PORT", "7001"))
    logger.info("MCP restaurant server listening on %s:%s", host, port)
    mcp.run(transport="sse", host=host, port=port)


if __name__ == "__main__":
    main()
