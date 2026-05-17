from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from backend.adapters.base import LLMAdapter
from backend.common.types import LLMRequest, LLMResponse, StreamChunk

AdapterItem = str | LLMResponse | Exception | Callable[[LLMRequest], str | LLMResponse]


def plan_json(goal: str = "LLM生成的目标", step_count: int = 3) -> str:
    steps = [
        {
            "step_id": index,
            "title": f"步骤{index}",
            "description": f"执行第 {index} 步。",
            "tools_hint": ["Read"],
        }
        for index in range(1, step_count + 1)
    ]
    return json.dumps(
        {
            "goal": goal,
            "approach": ["分析需求", "执行修改", "验证结果"],
            "data_structures": "",
            "steps": steps,
        },
        ensure_ascii=False,
    )


VALID_PLAN_JSON = json.dumps(
    {
        "goal": "LLM生成的目标",
        "approach": ["分析需求", "执行修改", "验证结果"],
        "data_structures": "",
        "steps": [
            {
                "step_id": 1,
                "title": "分析",
                "description": "分析用户需求和相关约束。",
                "tools_hint": ["Read"],
            },
            {
                "step_id": 2,
                "title": "实施",
                "description": "按计划执行必要修改。",
                "tools_hint": ["Write"],
            },
            {
                "step_id": 3,
                "title": "验证",
                "description": "运行验证并总结结果。",
                "tools_hint": ["Bash"],
            },
        ],
    },
    ensure_ascii=False,
)


class MockAdapter(LLMAdapter):
    def __init__(self, responses: list[AdapterItem] | None = None) -> None:
        self._responses = responses or [VALID_PLAN_JSON]
        self.requests: list[LLMRequest] = []

    async def test_connection(self) -> bool:
        return True

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self._responses) - 1)
        item = self._responses[index]
        if isinstance(item, Exception):
            raise item
        if callable(item):
            item = item(request)
        if isinstance(item, LLMResponse):
            return item
        return LLMResponse(content=item)

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        if False:
            yield StreamChunk(type="done")


async def approve_when_awaiting(
    runner: Any,
    task: asyncio.Task[Any] | None = None,
    timeout: float = 5.0,
) -> None:
    from backend.core.s01_agent_loop import PlanPhase

    attempts = max(int(timeout / 0.01), 1)
    for _ in range(attempts):
        if getattr(runner, "phase", None) == PlanPhase.AWAITING_APPROVAL:
            runner.approve()
            return
        if task is not None and task.done():
            return
        await asyncio.sleep(0.01)
    if task is None or not task.done():
        raise AssertionError("runner did not enter awaiting approval")


async def run_with_approval(runner: Any, message: str) -> Any:
    task = asyncio.create_task(runner.run(message))
    await approve_when_awaiting(runner, task)
    return await task


async def resume_with_approval(runner: Any) -> Any:
    task = asyncio.create_task(runner.resume_run())
    await approve_when_awaiting(runner, task)
    return await task
