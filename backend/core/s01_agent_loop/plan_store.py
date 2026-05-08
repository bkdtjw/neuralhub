from __future__ import annotations

import json
import re
import secrets
from datetime import datetime
from pathlib import Path

from .plan_models import ExecutionPlan, PlanStep, TodoState, TodoStep

_ADJECTIVES = ("brisk", "calm", "clear", "cosmic", "lunar", "prime", "rapid", "solid")
_VERBS = ("mapping", "plotting", "shaping", "sorting", "tracing", "weaving")
_NOUNS = ("anchor", "bridge", "matrix", "signal", "vector", "workflow")
_PLAN_PART_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FILE_PART_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_STEP_RE = re.compile(r"^### Step (\d+): (.+)$", re.MULTILINE)


def generate_plan_name() -> str:
    """Return a lowercase, filename-safe adjective-verb-noun plan name."""

    parts = (secrets.choice(_ADJECTIVES), secrets.choice(_VERBS), secrets.choice(_NOUNS))
    return "-".join(parts)


class PlanStore:
    def __init__(self, base_dir: str | None = None) -> None:
        self._base_dir = Path(base_dir or "data/plans")
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def save_plan(self, name: str, plan: ExecutionPlan) -> Path:
        path = self._path_for(name)
        path.write_text(_format_plan(name, plan, ""), encoding="utf-8")
        return path

    def update_plan(self, name: str, plan: ExecutionPlan) -> Path:
        path = self._path_for(name)
        old_content = path.read_text(encoding="utf-8") if path.exists() else ""
        old_log = _section_text(old_content, "Amendment Log")
        entry = f"- {_created_label()}: Version {plan.version}"
        amendment_log = "\n".join(item for item in (old_log.rstrip(), entry) if item)
        path.write_text(_format_plan(name, plan, amendment_log), encoding="utf-8")
        return path

    def read_plan(self, name: str) -> ExecutionPlan:
        content = self._path_for(name).read_text(encoding="utf-8")
        return ExecutionPlan(
            goal=_section_text(content, "Goal"),
            approach=_parse_approach(_section_text(content, "Approach")),
            data_structures=_section_text(content, "Data Structure"),
            steps=_parse_steps(_section_text(content, "Steps")),
            version=int(_meta_value(content, "Version") or "1"),
        )

    def list_plans(self) -> list[str]:
        return sorted(path.stem for path in self._base_dir.glob("*.md") if path.is_file())

    def _path_for(self, name: str) -> Path:
        _validate_plan_name(name)
        return self._base_dir / f"{name}.md"


class TodoStore:
    def __init__(self, base_dir: str | None = None) -> None:
        self._base_dir = Path(base_dir or "data/todos")
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def create(self, session_id: str, plan_name: str, steps: list[PlanStep]) -> TodoState:
        todo_steps = [TodoStep(id=step.step_id, title=step.title) for step in steps]
        state = TodoState(plan_name=plan_name, session_id=session_id, steps=todo_steps)
        self.update(session_id, plan_name, state)
        return state

    def update(self, session_id: str, plan_name: str, state: TodoState) -> None:
        self._path_for(session_id, plan_name).write_text(
            state.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def read(self, session_id: str, plan_name: str) -> TodoState | None:
        path = self._path_for(session_id, plan_name)
        if not path.exists():
            return None
        return TodoState.model_validate_json(path.read_text(encoding="utf-8"))

    def list_active(self) -> list[TodoState]:
        states: list[TodoState] = []
        for path in sorted(self._base_dir.glob("*.json")):
            try:
                state = TodoState.model_validate_json(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if state.status in {"executing", "paused"}:
                states.append(state)
        return states

    def _path_for(self, session_id: str, plan_name: str) -> Path:
        _validate_file_part(session_id, "session_id")
        _validate_plan_name(plan_name)
        return self._base_dir / f"{session_id}-plan-{plan_name}.json"


def _format_plan(
    name: str,
    plan: ExecutionPlan,
    amendment_log: str,
) -> str:
    lines = _format_plan_header(name, plan)
    for step in plan.steps:
        tools = json.dumps(step.tools_hint, ensure_ascii=False)
        lines += [f"### Step {step.step_id}: {step.title}", step.description, f"Tools: {tools}", ""]
    lines.extend(["## Amendment Log", amendment_log])
    return "\n".join(lines).rstrip() + "\n"


def _format_plan_header(name: str, plan: ExecutionPlan) -> list[str]:
    return [
        f"# {name}",
        "",
        "## Meta",
        f"- Version: {plan.version}",
        f"- Created: {_created_label()}",
        "",
        "## Goal",
        plan.goal,
        "",
        "## Approach",
        *[f"- {item}" for item in plan.approach],
        "",
        "## Data Structure",
        plan.data_structures,
        "",
        "## Steps",
    ]


def _section_text(content: str, heading: str) -> str:
    lines = content.splitlines()
    marker = f"## {heading}"
    try:
        start = next(index + 1 for index, line in enumerate(lines) if line.strip() == marker)
    except StopIteration:
        return ""
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end]).strip()


def _meta_value(content: str, key: str) -> str:
    for line in _section_text(content, "Meta").splitlines():
        if line.startswith(f"- {key}:"):
            return line.split(":", 1)[1].strip()
    return ""


def _parse_approach(raw: str) -> list[str]:
    return [line.removeprefix("- ").strip() for line in raw.splitlines() if line.strip()]


def _parse_steps(raw: str) -> list[PlanStep]:
    steps: list[PlanStep] = []
    matches = list(_STEP_RE.finditer(raw))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        block = raw[match.end() : end].strip("\n").splitlines()
        steps.append(_parse_step_block(int(match.group(1)), match.group(2).strip(), block))
    return steps


def _parse_step_block(step_id: int, title: str, block: list[str]) -> PlanStep:
    tools: list[str] = []
    description: list[str] = []
    for line in block:
        if line.startswith("Tools:"):
            tools = _parse_tools(line.removeprefix("Tools:").strip())
        else:
            description.append(line)
    text = "\n".join(description).strip()
    return PlanStep(step_id=step_id, title=title, description=text, tools_hint=tools)


def _parse_tools(raw: str) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
        return [str(item) for item in value] if isinstance(value, list) else []
    except json.JSONDecodeError:
        return [item.strip() for item in raw.split(",") if item.strip()]


def _created_label() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _validate_plan_name(name: str) -> None:
    if not _PLAN_PART_RE.fullmatch(name):
        raise ValueError(f"Invalid plan name: {name}")


def _validate_file_part(value: str, field_name: str) -> None:
    if not value or not _FILE_PART_RE.fullmatch(value):
        raise ValueError(f"Invalid {field_name}: {value}")


__all__ = ["PlanStore", "TodoStore", "generate_plan_name"]
