import asyncio
import os
import socket
import sys
import types
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from a2a.types import DataPart, Message, Part, Role, TextPart
from a2a.utils import new_task


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "AGENTS.md").exists():
            return parent
    raise RuntimeError("Repository root not found.")


def _is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True

async def _wait_for_port(host: str, port: int, timeout_s: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeError(f"Timed out waiting for {host}:{port}")
            await asyncio.sleep(0.2)


@asynccontextmanager
async def _run_process(cmd: list[str], env: dict[str, str]):
    process = await asyncio.create_subprocess_exec(
        *cmd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        yield process
    finally:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()


class _FakeTaskUpdater:
    def __init__(self) -> None:
        self.events: list[tuple[object, Message, bool]] = []

    async def update_status(self, state, message, final: bool = False) -> None:
        self.events.append((state, message, final))


def _extract_data_model_updates(events: list[tuple[object, Message, bool]]):
    updates = []
    for _, message, _ in events:
        for part in message.parts:
            if isinstance(part.root, DataPart):
                payload = part.root.data
                if isinstance(payload, dict) and "dataModelUpdate" in payload:
                    updates.append(payload["dataModelUpdate"])
    return updates


def _extract_score_values(update: dict) -> list[float]:
    scores: list[float] = []
    for item in update.get("contents", []):
        value_map = item.get("valueMap") or []
        for entry in value_map:
            if entry.get("key") == "score":
                score_value = entry.get("valueNumber")
                if score_value is not None:
                    scores.append(float(score_value))
    return scores


@pytest.mark.anyio
async def test_demo_pipeline_emits_progressive_updates() -> None:
    repo_root = _repo_root()
    restaurant_dir = repo_root / "samples/agent/adk/restaurant_finder"
    a2ui_src = repo_root / "a2a_agents/python/a2ui_extension/src"

    sys.path.insert(0, str(restaurant_dir))
    sys.path.insert(0, str(a2ui_src))

    fake_agent = types.ModuleType("agent")
    fake_agent.RestaurantAgent = object
    sys.modules.setdefault("agent", fake_agent)

    from agent_executor import RestaurantAgentExecutor

    mcp_port = 8000
    a2a_port = 8002
    if not _is_port_free(mcp_port):
        pytest.skip("MCP server port 8000 is already in use.")
    if not _is_port_free(a2a_port):
        pytest.skip("A2A rater port 8002 is already in use.")

    env_base = os.environ.copy()
    env_base["PYTHONPATH"] = os.pathsep.join(
        [str(restaurant_dir), str(a2ui_src), env_base.get("PYTHONPATH", "")]
    )

    mcp_env = dict(env_base)
    mcp_env["MCP_HOST"] = "127.0.0.1"
    mcp_env["MCP_PORT"] = str(mcp_port)

    a2a_env = dict(env_base)
    a2a_env["A2A_RATER_HOST"] = "127.0.0.1"
    a2a_env["A2A_RATER_PORT"] = str(a2a_port)

    async with _run_process(
        [sys.executable, "-m", "demos.mcp_restaurants_server.server"], mcp_env
    ):
        await _wait_for_port("127.0.0.1", mcp_port)
        async with _run_process(
            [sys.executable, "-m", "demos.a2a_restaurant_rater.server"], a2a_env
        ):
            await _wait_for_port("127.0.0.1", a2a_port)

            executor = RestaurantAgentExecutor.__new__(RestaurantAgentExecutor)
            executor._mcp_sse_url = f"http://127.0.0.1:{mcp_port}/sse"
            executor._a2a_rater_url = f"http://127.0.0.1:{a2a_port}/"

            updater = _FakeTaskUpdater()
            message = Message(
                kind="message",
                message_id=str(uuid.uuid4()),
                role=Role.user,
                parts=[Part(root=TextPart(text="demo"))],
            )
            task = new_task(message)

            await executor._run_demo_pipeline(updater, task)

            updates = _extract_data_model_updates(updater.events)
            status_updates = [u for u in updates if u.get("path") == "/status"]
            results_updates = [u for u in updates if u.get("path") == "/results"]

            assert len(status_updates) >= 2
            assert len(results_updates) >= 2

            scored = False
            for update in results_updates:
                if any(value > 0 for value in _extract_score_values(update)):
                    scored = True
                    break

            assert scored
