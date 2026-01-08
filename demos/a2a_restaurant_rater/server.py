import json
import logging
import os
from typing import Any, Dict, List, Optional

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    DataPart,
    Part,
    Task,
    TaskState,
    TextPart,
    UnsupportedOperationError,
)
from a2a.utils import new_agent_parts_message, new_task
from a2a.utils.errors import ServerError
from starlette.middleware.cors import CORSMiddleware
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


def _extract_payload(context: RequestContext) -> Optional[Dict[str, Any]]:
    if context.message and context.message.parts:
        for part in context.message.parts:
            if isinstance(part.root, DataPart) and isinstance(part.root.data, dict):
                return part.root.data
            if isinstance(part.root, TextPart):
                text = part.root.text.strip()
                if text:
                    try:
                        parsed = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, dict):
                        return parsed
    return None


class RestaurantRaterExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        payload = _extract_payload(context)
        task = context.current_task

        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        if not payload:
            message = "Expected JSON payload with 'restaurants' and optional 'prefs'."
            await updater.update_status(
                TaskState.completed,
                new_agent_parts_message([Part(root=TextPart(text=message))], task.context_id, task.id),
                final=True,
            )
            return

        restaurants = payload.get("restaurants", [])
        if not isinstance(restaurants, list):
            restaurants = []
        prefs = payload.get("prefs") or {}
        if not isinstance(prefs, dict):
            prefs = {}

        enriched = [_rate_restaurant(restaurant, prefs) for restaurant in restaurants]
        response = {"restaurants": enriched}

        result_part = Part(
            root=DataPart(
                data=response,
                metadata={"mimeType": "application/json"},
            )
        )

        await updater.update_status(
            TaskState.completed,
            new_agent_parts_message([result_part], task.context_id, task.id),
            final=True,
        )

    async def cancel(self, request: RequestContext, event_queue: EventQueue) -> Task | None:
        raise ServerError(error=UnsupportedOperationError())


def main() -> None:
    host = os.getenv("A2A_RATER_HOST", "localhost")
    port = int(os.getenv("A2A_RATER_PORT", "8002"))
    base_url = f"http://{host}:{port}"

    capabilities = AgentCapabilities(streaming=False)
    skill = AgentSkill(
        id=TOOL_NAME,
        name="Rate Restaurants Tool",
        description="Scores restaurants deterministically and marks recommendations based on preferences.",
        tags=["restaurant", "rating", "scoring"],
        examples=["Score these restaurants for Italian cuisine under price level 2."],
    )

    agent_card = AgentCard(
        name="Restaurant Rater Agent",
        description="Deterministic restaurant rating agent (no external calls).",
        url=base_url,
        version="1.0.0",
        default_input_modes=SUPPORTED_CONTENT_TYPES,
        default_output_modes=SUPPORTED_CONTENT_TYPES,
        capabilities=capabilities,
        skills=[skill],
    )

    agent_executor = RestaurantRaterExecutor()

    request_handler = DefaultRequestHandler(
        agent_executor=agent_executor,
        task_store=InMemoryTaskStore(),
    )

    server = A2AStarletteApplication(agent_card=agent_card, http_handler=request_handler)
    app = server.build()

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
