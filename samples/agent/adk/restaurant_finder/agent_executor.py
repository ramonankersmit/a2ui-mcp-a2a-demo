# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import json
import logging
import os
import time
import uuid
from typing import Any

import httpx
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    DataPart,
    Part,
    Task,
    TaskState,
    TextPart,
    UnsupportedOperationError,
)
from a2a.utils import (
    new_agent_parts_message,
    new_agent_text_message,
    new_task,
)
from a2a.utils.errors import ServerError
from a2ui.a2ui_extension import create_a2ui_part, try_activate_a2ui_extension
from agent import RestaurantAgent

logger = logging.getLogger(__name__)

DEMO_SURFACE_ID = "default"
DEMO_MCP_STEP = "mcp_search"
DEMO_AVAILABILITY_STEP = "mcp_availability"
DEMO_A2A_STEP = "a2a_rank"
DEMO_DONE_STEP = "done"


def _extract_tool_payload(result: Any) -> Any:
    if getattr(result, "structuredContent", None) is not None:
        return result.structuredContent

    content = getattr(result, "content", []) or []
    for item in content:
        text = getattr(item, "text", None)
        if not text:
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            continue
    return None


def _availability_value_map(slots: list[str]) -> list[dict[str, Any]]:
    return [
        {"key": str(index + 1), "valueString": slot} for index, slot in enumerate(slots)
    ]


def _restaurant_value_map(restaurant: dict[str, Any]) -> list[dict[str, Any]]:
    availability = restaurant.get("availability") or []
    availability_text = ", ".join(availability) if availability else "No availability yet"
    rating = float(restaurant.get("rating") or 0)
    distance_km = float(restaurant.get("distance_km") or 0)
    price_level = int(restaurant.get("price_level") or 0)
    score = restaurant.get("score")
    score_value = float(score) if score is not None else 0
    score_text = f"Score: {int(score_value)}" if score is not None else "Score: --"
    recommended = bool(restaurant.get("recommended"))
    recommended_text = "Recommended" if recommended else "Not recommended"
    meta = (
        f"{restaurant.get('cuisine', 'Unknown')} · "
        f"Rating {rating:.1f} · {distance_km:.1f} km · "
        f"Price level {price_level}"
    )

    return [
        {"key": "id", "valueString": str(restaurant.get("id", ""))},
        {"key": "name", "valueString": str(restaurant.get("name", ""))},
        {"key": "cuisine", "valueString": str(restaurant.get("cuisine", ""))},
        {"key": "rating", "valueNumber": rating},
        {"key": "distance_km", "valueNumber": distance_km},
        {"key": "price_level", "valueNumber": price_level},
        {"key": "availability", "valueMap": _availability_value_map(availability)},
        {"key": "availabilityText", "valueString": availability_text},
        {"key": "score", "valueNumber": score_value},
        {"key": "scoreText", "valueString": score_text},
        {"key": "recommended", "valueBoolean": recommended},
        {"key": "recommendedText", "valueString": recommended_text},
        {"key": "rationale", "valueString": str(restaurant.get("rationale", ""))},
        {"key": "meta", "valueString": meta},
    ]


def _results_value_map(restaurants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"key": f"item{index + 1}", "valueMap": _restaurant_value_map(restaurant)}
        for index, restaurant in enumerate(restaurants)
    ]


def _status_value_map(loading: bool, message: str, step: str) -> list[dict[str, Any]]:
    return [
        {"key": "loading", "valueBoolean": loading},
        {"key": "message", "valueString": message},
        {"key": "step", "valueString": step},
    ]


def _build_data_model_update(path: str, contents: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "dataModelUpdate": {
            "surfaceId": DEMO_SURFACE_ID,
            "path": path,
            "contents": contents,
        }
    }


def _build_demo_surface_messages() -> list[dict[str, Any]]:
    return [
        {
            "beginRendering": {
                "surfaceId": DEMO_SURFACE_ID,
                "root": "demo-root",
                "styles": {"primaryColor": "#3B82F6", "font": "Roboto"},
            }
        },
        {
            "surfaceUpdate": {
                "surfaceId": DEMO_SURFACE_ID,
                "components": [
                    {
                        "id": "demo-root",
                        "component": {
                            "Column": {
                                "children": {
                                    "explicitList": [
                                        "demo-title",
                                        "demo-status",
                                        "demo-step",
                                        "demo-list",
                                    ]
                                }
                            }
                        },
                    },
                    {
                        "id": "demo-title",
                        "component": {
                            "Text": {
                                "usageHint": "h1",
                                "text": {
                                    "literalString": "Restaurant Demo (MCP + A2A)"
                                },
                            }
                        },
                    },
                    {
                        "id": "demo-status",
                        "component": {
                            "Text": {"usageHint": "h3", "text": {"path": "/status/message"}}
                        },
                    },
                    {
                        "id": "demo-step",
                        "component": {"Text": {"text": {"path": "/status/step"}}},
                    },
                    {
                        "id": "demo-list",
                        "component": {
                            "List": {
                                "direction": "vertical",
                                "children": {
                                    "template": {
                                        "componentId": "demo-card-template",
                                        "dataBinding": "/results",
                                    }
                                },
                            }
                        },
                    },
                    {
                        "id": "demo-card-template",
                        "component": {"Card": {"child": "demo-card-column"}},
                    },
                    {
                        "id": "demo-card-column",
                        "component": {
                            "Column": {
                                "children": {
                                    "explicitList": [
                                        "demo-name",
                                        "demo-meta",
                                        "demo-availability",
                                        "demo-score",
                                        "demo-recommended",
                                        "demo-rationale",
                                    ]
                                }
                            }
                        },
                    },
                    {
                        "id": "demo-name",
                        "component": {"Text": {"usageHint": "h3", "text": {"path": "name"}}},
                    },
                    {
                        "id": "demo-meta",
                        "component": {"Text": {"text": {"path": "meta"}}},
                    },
                    {
                        "id": "demo-availability",
                        "component": {"Text": {"text": {"path": "availabilityText"}}},
                    },
                    {
                        "id": "demo-score",
                        "component": {"Text": {"text": {"path": "scoreText"}}},
                    },
                    {
                        "id": "demo-recommended",
                        "component": {"Text": {"text": {"path": "recommendedText"}}},
                    },
                    {
                        "id": "demo-rationale",
                        "component": {"Text": {"text": {"path": "rationale"}}},
                    },
                ],
            }
        },
    ]


class RestaurantAgentExecutor(AgentExecutor):
    """Restaurant AgentExecutor Example."""

    def __init__(self, base_url: str):
        # Instantiate two agents: one for UI and one for text-only.
        # The appropriate one will be chosen at execution time.
        self.ui_agent = RestaurantAgent(base_url=base_url, use_ui=True)
        self.text_agent = RestaurantAgent(base_url=base_url, use_ui=False)
        self._mcp_sse_url = os.getenv("MCP_SSE_URL", "http://127.0.0.1:8000/sse")
        self._a2a_rater_url = os.getenv("A2A_RATER_URL", "http://localhost:8002/")

    async def _send_demo_update(
        self,
        updater: TaskUpdater,
        task: Task,
        messages: list[dict[str, Any]],
        state: TaskState = TaskState.working,
        final: bool = False,
    ) -> None:
        parts = [create_a2ui_part(message) for message in messages]
        await updater.update_status(
            state,
            new_agent_parts_message(parts, task.context_id, task.id),
            final=final,
        )

    async def _run_demo_pipeline(
        self, updater: TaskUpdater, task: Task
    ) -> None:
        start_messages = _build_demo_surface_messages()
        start_messages.append(
            _build_data_model_update(
                "/",
                [
                    {
                        "key": "status",
                        "valueMap": _status_value_map(
                            True, "Searching via MCP...", DEMO_MCP_STEP
                        ),
                    },
                    {"key": "results", "valueMap": []},
                ],
            )
        )
        await self._send_demo_update(updater, task, start_messages)

        restaurants: list[dict[str, Any]] = []
        try:
            search_start = time.perf_counter()
            logger.info("DEMO: MCP search")
            async with sse_client(self._mcp_sse_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    search_result = await session.call_tool(
                        "search_restaurants", {"query": "*", "location": "demo"}
                    )
                    restaurants_payload = _extract_tool_payload(search_result)
                    restaurants = (
                        restaurants_payload
                        if isinstance(restaurants_payload, list)
                        else []
                    )

                    search_duration = time.perf_counter() - search_start
                    logger.info(
                        "DEMO: MCP search completed in %.2fs", search_duration
                    )

                    partial = restaurants[:3]
                    await self._send_demo_update(
                        updater,
                        task,
                        [
                            _build_data_model_update(
                                "/status",
                                _status_value_map(
                                    True,
                                    "Found 3, fetching more...",
                                    DEMO_MCP_STEP,
                                ),
                            ),
                            _build_data_model_update(
                                "/results", _results_value_map(partial)
                            ),
                        ],
                    )

                    availability_start = time.perf_counter()
                    logger.info("DEMO: MCP availability")

                    await self._send_demo_update(
                        updater,
                        task,
                        [
                            _build_data_model_update(
                                "/status",
                                _status_value_map(
                                    True, "Checking availability...", DEMO_AVAILABILITY_STEP
                                ),
                            ),
                            _build_data_model_update(
                                "/results", _results_value_map(restaurants)
                            ),
                        ],
                    )

                    date = datetime.date.today().isoformat()
                    for restaurant in restaurants[:3]:
                        availability_result = await session.call_tool(
                            "get_availability",
                            {"restaurant_id": restaurant.get("id"), "date": date},
                        )
                        availability_payload = _extract_tool_payload(
                            availability_result
                        )
                        if isinstance(availability_payload, list):
                            restaurant["availability"] = availability_payload

                        await self._send_demo_update(
                            updater,
                            task,
                            [_build_data_model_update("/results", _results_value_map(restaurants))],
                        )

                    availability_duration = time.perf_counter() - availability_start
                    logger.info(
                        "DEMO: MCP availability completed in %.2fs",
                        availability_duration,
                    )

            logger.info("DEMO: A2A rank")
            rank_start = time.perf_counter()
            await self._send_demo_update(
                updater,
                task,
                [
                    _build_data_model_update(
                        "/status",
                        _status_value_map(True, "Ranking with A2A...", DEMO_A2A_STEP),
                    )
                ],
            )

            prefs = {"cuisine": "French", "max_price_level": 3}
            request_payload = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "message/send",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [
                            {
                                "kind": "data",
                                "data": {
                                    "restaurants": restaurants,
                                    "prefs": prefs,
                                },
                            }
                        ],
                    }
                },
            }

            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    self._a2a_rater_url, json=request_payload
                )
                response.raise_for_status()
                response_payload = response.json()

            ranked_restaurants = (
                response_payload.get("result", {})
                .get("status", {})
                .get("message", {})
                .get("parts", [{}])[0]
                .get("data", {})
                .get("restaurants", [])
            )

            if isinstance(ranked_restaurants, list):
                ranked_by_id = {item.get("id"): item for item in ranked_restaurants}
                for restaurant in restaurants:
                    ranked = ranked_by_id.get(restaurant.get("id"))
                    if ranked:
                        restaurant.update(
                            {
                                "score": ranked.get("score"),
                                "rationale": ranked.get("rationale"),
                                "recommended": ranked.get("recommended"),
                            }
                        )

            restaurants.sort(
                key=lambda item: float(item.get("score") or 0), reverse=True
            )

            rank_duration = time.perf_counter() - rank_start
            logger.info("DEMO: A2A rank completed in %.2fs", rank_duration)

            await self._send_demo_update(
                updater,
                task,
                [
                    _build_data_model_update(
                        "/status",
                        _status_value_map(False, "Ranked results", DEMO_DONE_STEP),
                    ),
                    _build_data_model_update("/results", _results_value_map(restaurants)),
                ],
                state=TaskState.input_required,
            )
        except Exception as exc:
            logger.exception("DEMO: pipeline failed", exc_info=exc)
            await self._send_demo_update(
                updater,
                task,
                [
                    _build_data_model_update(
                        "/status",
                        _status_value_map(
                            False,
                            "Demo failed. Check server logs for details.",
                            DEMO_DONE_STEP,
                        ),
                    )
                ],
                state=TaskState.input_required,
            )

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        query = ""
        ui_event_part = None
        action = None

        logger.info(
            f"--- Client requested extensions: {context.requested_extensions} ---"
        )
        use_ui = try_activate_a2ui_extension(context)

        # Determine which agent to use based on whether the a2ui extension is active.
        if use_ui:
            agent = self.ui_agent
            logger.info(
                "--- AGENT_EXECUTOR: A2UI extension is active. Using UI agent. ---"
            )
        else:
            agent = self.text_agent
            logger.info(
                "--- AGENT_EXECUTOR: A2UI extension is not active. Using text agent. ---"
            )

        if context.message and context.message.parts:
            logger.info(
                f"--- AGENT_EXECUTOR: Processing {len(context.message.parts)} message parts ---"
            )
            for i, part in enumerate(context.message.parts):
                if isinstance(part.root, DataPart):
                    if "userAction" in part.root.data:
                        logger.info(f"  Part {i}: Found a2ui UI ClientEvent payload.")
                        ui_event_part = part.root.data["userAction"]
                    else:
                        logger.info(f"  Part {i}: DataPart (data: {part.root.data})")
                elif isinstance(part.root, TextPart):
                    logger.info(f"  Part {i}: TextPart (text: {part.root.text})")
                else:
                    logger.info(f"  Part {i}: Unknown part type ({type(part.root)})")

        if ui_event_part:
            logger.info(f"Received a2ui ClientEvent: {ui_event_part}")
            action = ui_event_part.get("name") or ui_event_part.get("actionName")
            ctx = ui_event_part.get("context", {})

            if action == "demo_mcp_a2a":
                logger.info("--- AGENT_EXECUTOR: Starting demo MCP + A2A flow. ---")

            elif action == "book_restaurant":
                restaurant_name = ctx.get("restaurantName", "Unknown Restaurant")
                address = ctx.get("address", "Address not provided")
                image_url = ctx.get("imageUrl", "")
                query = f"USER_WANTS_TO_BOOK: {restaurant_name}, Address: {address}, ImageURL: {image_url}"

            elif action == "submit_booking":
                restaurant_name = ctx.get("restaurantName", "Unknown Restaurant")
                party_size = ctx.get("partySize", "Unknown Size")
                reservation_time = ctx.get("reservationTime", "Unknown Time")
                dietary_reqs = ctx.get("dietary", "None")
                image_url = ctx.get("imageUrl", "")
                query = f"User submitted a booking for {restaurant_name} for {party_size} people at {reservation_time} with dietary requirements: {dietary_reqs}. The image URL is {image_url}"

            else:
                query = f"User submitted an event: {action} with data: {ctx}"
        else:
            logger.info("No a2ui UI event part found. Falling back to text input.")
            query = context.get_user_input()

        logger.info(f"--- AGENT_EXECUTOR: Final query for LLM: '{query}' ---")

        task = context.current_task

        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        if action == "demo_mcp_a2a" and use_ui:
            await self._run_demo_pipeline(updater, task)
            return

        async for item in agent.stream(query, task.context_id):
            is_task_complete = item["is_task_complete"]
            if not is_task_complete:
                await updater.update_status(
                    TaskState.working,
                    new_agent_text_message(item["updates"], task.context_id, task.id),
                )
                continue

            final_state = (
                TaskState.completed
                if action == "submit_booking"
                else TaskState.input_required
            )

            content = item["content"]
            final_parts = []
            if "---a2ui_JSON---" in content:
                logger.info("Splitting final response into text and UI parts.")
                text_content, json_string = content.split("---a2ui_JSON---", 1)

                if text_content.strip():
                    final_parts.append(Part(root=TextPart(text=text_content.strip())))

                if json_string.strip():
                    try:
                        json_string_cleaned = (
                            json_string.strip().lstrip("```json").rstrip("```").strip()
                        )
                        # The new protocol sends a stream of JSON objects.
                        # For this example, we'll assume they are sent as a list in the final response.
                        json_data = json.loads(json_string_cleaned)

                        if isinstance(json_data, list):
                            logger.info(
                                f"Found {len(json_data)} messages. Creating individual DataParts."
                            )
                            for message in json_data:
                                final_parts.append(create_a2ui_part(message))
                        else:
                            # Handle the case where a single JSON object is returned
                            logger.info(
                                "Received a single JSON object. Creating a DataPart."
                            )
                            final_parts.append(create_a2ui_part(json_data))

                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse UI JSON: {e}")
                        final_parts.append(Part(root=TextPart(text=json_string)))
            else:
                final_parts.append(Part(root=TextPart(text=content.strip())))

            logger.info("--- FINAL PARTS TO BE SENT ---")
            for i, part in enumerate(final_parts):
                logger.info(f"  - Part {i}: Type = {type(part.root)}")
                if isinstance(part.root, TextPart):
                    logger.info(f"    - Text: {part.root.text[:200]}...")
                elif isinstance(part.root, DataPart):
                    logger.info(f"    - Data: {str(part.root.data)[:200]}...")
            logger.info("-----------------------------")

            await updater.update_status(
                final_state,
                new_agent_parts_message(final_parts, task.context_id, task.id),
                final=(final_state == TaskState.completed),
            )
            break

    async def cancel(
        self, request: RequestContext, event_queue: EventQueue
    ) -> Task | None:
        raise ServerError(error=UnsupportedOperationError())
