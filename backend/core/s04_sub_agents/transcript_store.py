from __future__ import annotations

import time
from collections import OrderedDict

from pydantic import BaseModel, Field

_MAX_RUNS = 40
_MAX_ENTRIES_PER_AGENT = 120
_MAX_ENTRY_CHARS = 6000


class TranscriptEntry(BaseModel):
    kind: str = "message"
    content: str = ""
    is_error: bool = False
    ts: float = 0.0


class AgentTranscript(BaseModel):
    role: str
    stage: int | None = None
    status: str = "pending"
    error: str = ""
    dropped: int = 0
    started_at: float = 0.0
    updated_at: float = 0.0
    entries: list[TranscriptEntry] = Field(default_factory=list)


class RunTranscript(BaseModel):
    run_id: str
    source: str = ""
    message: str = ""
    started_at: float = 0.0
    updated_at: float = 0.0
    agents: dict[str, AgentTranscript] = Field(default_factory=dict)
    order: list[str] = Field(default_factory=list)


class RunSummary(BaseModel):
    run_id: str
    source: str = ""
    message: str = ""
    started_at: float = 0.0
    updated_at: float = 0.0
    roles: list[str] = Field(default_factory=list)


def clip_content(text: object, limit: int = _MAX_ENTRY_CHARS) -> str:
    value = str(text)
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


class SubAgentTranscriptStore:
    """进程内 LRU 存储：保留最近若干次子 agent 运行的完整活动转录。

    与 WS 上的 160 字符 preview 事件互补：preview 负责实时滚动，这里保
    全文（单条上限 _MAX_ENTRY_CHARS），供前端点开某个子 agent 时查询。
    """

    def __init__(
        self,
        max_runs: int = _MAX_RUNS,
        max_entries_per_agent: int = _MAX_ENTRIES_PER_AGENT,
        max_entry_chars: int = _MAX_ENTRY_CHARS,
    ) -> None:
        self._runs: OrderedDict[str, RunTranscript] = OrderedDict()
        self._max_runs = max_runs
        self._max_entries = max_entries_per_agent
        self._max_chars = max_entry_chars

    def record_spawned(
        self,
        run_id: str,
        source: str,
        roles: list[str],
        stage: int | None = None,
        message: str = "",
    ) -> None:
        run = self._touch_run(run_id, source)
        if message and stage is None:
            run.message = message
        for role in roles:
            agent = self._touch_agent(run, role, stage)
            # 编排的运行级事件只是预告全员名单，agent 要等自己的阶段启动才算运行中。
            if agent.status == "pending" and (stage is not None or source != "orchestrate"):
                agent.status = "running"

    def record_entry(
        self,
        run_id: str,
        source: str,
        role: str,
        kind: str,
        content: object,
        stage: int | None = None,
        is_error: bool = False,
    ) -> None:
        run = self._touch_run(run_id, source)
        agent = self._touch_agent(run, role, stage)
        if agent.status == "pending":
            agent.status = "running"
        agent.entries.append(
            TranscriptEntry(
                kind=kind,
                content=clip_content(content, self._max_chars),
                is_error=is_error,
                ts=run.updated_at,
            )
        )
        if len(agent.entries) > self._max_entries:
            agent.entries.pop(0)
            agent.dropped += 1

    def record_done(
        self,
        run_id: str,
        source: str,
        role: str,
        stage: int | None = None,
        error: str = "",
        skipped: bool = False,
    ) -> None:
        run = self._touch_run(run_id, source)
        agent = self._touch_agent(run, role, stage)
        agent.status = "skipped" if skipped else ("failed" if error else "done")
        agent.error = clip_content(error, self._max_chars) if error else ""

    def get_run(self, run_id: str) -> RunTranscript | None:
        return self._runs.get(run_id)

    def get_agent(self, run_id: str, role: str) -> AgentTranscript | None:
        run = self._runs.get(run_id)
        return None if run is None else run.agents.get(role)

    def list_runs(self) -> list[RunSummary]:
        return [
            RunSummary(
                run_id=run.run_id,
                source=run.source,
                message=run.message,
                started_at=run.started_at,
                updated_at=run.updated_at,
                roles=list(run.order),
            )
            for run in reversed(self._runs.values())
        ]

    def clear(self) -> None:
        self._runs.clear()

    def _touch_run(self, run_id: str, source: str) -> RunTranscript:
        now = time.time()
        run = self._runs.get(run_id)
        if run is None:
            run = RunTranscript(run_id=run_id, source=source, started_at=now)
            self._runs[run_id] = run
        run.updated_at = now
        self._runs.move_to_end(run_id)
        while len(self._runs) > self._max_runs:
            self._runs.popitem(last=False)
        return run

    def _touch_agent(self, run: RunTranscript, role: str, stage: int | None) -> AgentTranscript:
        agent = run.agents.get(role)
        if agent is None:
            agent = AgentTranscript(role=role, stage=stage, started_at=run.updated_at)
            run.agents[role] = agent
            run.order.append(role)
        if stage is not None and agent.stage is None:
            agent.stage = stage
        agent.updated_at = run.updated_at
        return agent


_STORE = SubAgentTranscriptStore()


def get_sub_agent_transcript_store() -> SubAgentTranscriptStore:
    return _STORE


__all__ = [
    "AgentTranscript",
    "RunSummary",
    "RunTranscript",
    "SubAgentTranscriptStore",
    "TranscriptEntry",
    "clip_content",
    "get_sub_agent_transcript_store",
]
