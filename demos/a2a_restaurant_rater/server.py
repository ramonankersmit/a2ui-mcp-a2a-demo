import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
import uvicorn

logger = logging.getLogger("a2a_restaurant_rater")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

SUPPORTED_CONTENT_TYPES = ["application/json", "text/plain"]
TOOL_NAME = "rate_restaurants"


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp_score(value: int) -> int:
    return max(0, min(100, value))


def _distance_bonus(distance_km: float) -> int:
    return max(0, int(round(10 - distance_km * 2)))


def _price_penalty(price_level: int, max_price_level: Optional[int]) -> int:
    if max_price_level is None or price_level <= max_price_level:
        return 0
    return int((price_level - max_price_level) * 12)


def _cuisine_bonus(cuisine: Optional[str], preferred_cuisine: Optional[str]) -> int:
    if not cuisine or not preferred_cuisine:
        return 0
    if cuisine.strip().lower() == preferred_cuisine.strip().lower():
        return 8
    return 0


def _rate_restaurant(restaurant: Dict[str, Any], prefs: Dict[str, Any]) -> Dict[str, Any]:
    rating = _coerce_float(restaurant.get("rating"))
    base_score = _clamp_score(int(round(rating * 20)))

    distance_km = _coerce_float(restaurant.get("distance_km"))
    price_level = _coerce_int(restaurant.get("price_level"))

    max_price_level = prefs.get("max_price_level")
    pref_cuisine = prefs.get("cuisine")

    distance_bonus = _distance_bonus(distance_km)
    cuisine_bonus = _cuisine_bonus(restaurant.get("cuisine"), pref_cuisine)
    price_penalty = _price_penalty(price_level, _coerce_int(max_price_level, 0) if max_price_level is not None else None)

    score = _clamp_score(base_score + distance_bonus + cuisine_bonus - price_penalty)

    adjustments: List[str] = []
    if distance_bonus:
        adjustments.append(f"+{distance_bonus} for proximity")
    if cuisine_bonus:
        adjustments.append(f"+{cuisine_bonus} for cuisine match")
    if price_penalty:
        adjustments.append(f"-{price_penalty} for price above preference")

    if adjustments:
        rationale = (
            f"Base score {base_score} from rating {rating:.1f}. "
            f"Adjustments: {', '.join(adjustments)}."
        )
    else:
        rationale = f"Base score {base_score} from rating {rating:.1f}. No preference adjustments applied."

    enriched = dict(restaurant)
    enriched["score"] = int(score)
    enriched["rationale"] = rationale
    enriched["recommended"] = score >= 80
    return enriched


def _extract_payload(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    parts = message.get("parts") or []
    for part in parts:
        if part.get("kind") == "data" and isinstance(part.get("data"), dict):
            return part["data"]
        if part.get("kind") == "text":
            text = str(part.get("text", "")).strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def _build_agent_card(base_url: str) -> Dict[str, Any]:
    return {
        "name": "Restaurant Rater Agent",
        "description": "Deterministic restaurant rating agent (no external calls).",
        "url": base_url,
        "version": "1.0.0",
        "default_input_modes": SUPPORTED_CONTENT_TYPES,
        "default_output_modes": SUPPORTED_CONTENT_TYPES,
        "capabilities": {"streaming": False},
        "skills": [
            {
                "id": TOOL_NAME,
                "name": "Rate Restaurants Tool",
                "description": "Scores restaurants deterministically and marks recommendations based on preferences.",
                "tags": ["restaurant", "rating", "scoring"],
                "examples": [
                    "Score these restaurants for Italian cuisine under price level 2."
                ],
            }
        ],
    }


def _build_task_response(response: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    task_id = str(uuid.uuid4())
    context_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "kind": "task",
            "id": task_id,
            "contextId": context_id,
            "status": {
                "state": "completed",
                "message": {
                    "kind": "message",
                    "messageId": message_id,
                    "role": "assistant",
                    "parts": [
                        {
                            "kind": "data",
                            "data": response,
                            "metadata": {"mimeType": "application/json"},
                        }
                    ],
                },
            },
        },
    }


async def handle_agent_card(request: Request) -> JSONResponse:
    return JSONResponse(request.app.state.agent_card)


async def handle_jsonrpc(request: Request) -> JSONResponse | PlainTextResponse:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return PlainTextResponse("Invalid JSON payload.", status_code=400)

    if payload.get("jsonrpc") != "2.0" or payload.get("method") != "sendMessage":
        return PlainTextResponse("Unsupported JSON-RPC request.", status_code=400)

    request_id = str(payload.get("id") or "")
    message = payload.get("params", {}).get("message")
    if not isinstance(message, dict):
        return PlainTextResponse("Missing params.message.", status_code=400)

    message_payload = _extract_payload(message)
    if not message_payload:
        error_response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32602,
                "message": "Expected JSON payload with 'restaurants' and optional 'prefs'.",
            },
        }
        return JSONResponse(error_response, status_code=200)

    restaurants = message_payload.get("restaurants", [])
    if not isinstance(restaurants, list):
        restaurants = []
    prefs = message_payload.get("prefs") or {}
    if not isinstance(prefs, dict):
        prefs = {}

    enriched = [_rate_restaurant(restaurant, prefs) for restaurant in restaurants]
    response = {"restaurants": enriched}
    return JSONResponse(_build_task_response(response, request_id))


def main() -> None:
    host = os.getenv("A2A_RATER_HOST", "localhost")
    port = int(os.getenv("A2A_RATER_PORT", "8002"))
    base_url = f"http://{host}:{port}"
    agent_card = _build_agent_card(base_url)

    app = Starlette(
        routes=[
            Route("/", handle_jsonrpc, methods=["POST"]),
            Route("/.well-known/agent-card.json", handle_agent_card, methods=["GET"]),
        ]
    )
    app.state.agent_card = agent_card

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    logger.info("A2A restaurant rater listening on %s", base_url)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
