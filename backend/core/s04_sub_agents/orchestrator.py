from __future__ import annotations

import asyncio

from backend.adapters.base import LLMAdapter
from backend.common.errors import AgentError
from backend.common.types import AgentTask, SimplePlan, SubAgentResult, ToolResult, resolve_stages
from backend.core.s02_tools import ToolRegistry

from .agent_definition import AgentDefinitionLoader
from .isolated_runner import run_isolated_agent
from .orchestrator_report import coerce_result, format_report, skip_result
from .progress import SubAgentProgressEmitter
from .runtime_models import IsolatedAgentRun, IsolatedAgentRuntime, OrchestratorConfig


class OrchestrationError(AgentError):
    def __init__(self, message: str) -> None:
        super().__init__(code="ORCHESTRATION_ERROR", message=message)


class Orchestrator:
    """Execute a simple multi-agent plan with automatic stage resolution."""

    def __init__(
        self,
        adapter: LLMAdapter,
        parent_registry: ToolRegistry,
        config: OrchestratorConfig,
        progress: SubAgentProgressEmitter | None = None,
    ) -> None:
        self._runtime = IsolatedAgentRuntime(
            adapter=adapter,
            parent_registry=parent_registry,
            config=config,
        )
        self._definition_loader = AgentDefinitionLoader(config.agents_dir)
        self._max_parallel_agents = config.max_parallel_agents
        self._sem: asyncio.Semaphore | None = None
        self._progress = progress or SubAgentProgressEmitter(None, "orchestrate")
        self._done = 0
        self._total = 0

    async def execute(self, plan: SimplePlan) -> ToolResult:
        try:
            stages = resolve_stages(plan.tasks)
            task_map = {task.role: task for task in plan.tasks}
            self._done, self._total = 0, len(plan.tasks)
            await self._progress.spawned(
                total=self._total,
                specs=[task.role for task in plan.tasks],
                message=f"多 Agent 编排启动：共 {len(stages)} 个阶段、{self._total} 个子任务",
            )
            previous_outputs: dict[str, str] = {}
            failed_roles: set[str] = set()
            skipped_roles: set[str] = set()
            results: list[SubAgentResult] = []
            for stage in stages:
                stage_results = await self._run_stage(
                    stage.stage_id, stage.task_roles, task_map, previous_outputs, failed_roles, skipped_roles
                )
                results.extend(stage_results)
                for result in stage_results:
                    # 只有成功结果才作为依赖注入下游；失败/跳过的错误文本不进 previous_outputs。
                    if result.is_error:
                        failed_roles.add(result.role)
                    else:
                        previous_outputs[result.role] = result.output
            return ToolResult(
                output=format_report(stages, results, skipped_roles),
                is_error=any(item.is_error for item in results),
            )
        except OrchestrationError:
            raise
        except ValueError as exc:
            raise OrchestrationError(str(exc)) from exc
        except Exception as exc:
            raise OrchestrationError(str(exc)) from exc

    def _ensure_semaphore(self) -> asyncio.Semaphore:
        # 惰性创建：__init__ 可能不在事件循环内，Semaphore 需绑定运行中的 loop。
        if self._sem is None:
            self._sem = asyncio.Semaphore(self._max_parallel_agents)
        return self._sem

    async def _run_stage(
        self,
        stage_id: int,
        task_roles: list[str],
        task_map: dict[str, AgentTask],
        previous_outputs: dict[str, str],
        failed_roles: set[str],
        skipped_roles: set[str],
    ) -> list[SubAgentResult]:
        sem = self._ensure_semaphore()

        async def _run_one(role_name: str, run: IsolatedAgentRun) -> SubAgentResult:
            async with sem:
                result = await run_isolated_agent(
                    run, self._runtime, on_event=self._progress.child_observer(role_name, stage_id)
                )
            await self._emit_done(stage_id, role_name, result)
            return result

        results_by_role: dict[str, SubAgentResult] = {}
        run_roles: list[str] = []
        for role_name in task_roles:
            failed_deps = [dep for dep in task_map[role_name].depends_on if dep in failed_roles]
            if failed_deps:
                # 上游依赖失败：短路——不注入错误文本、不 spawn，直接产出跳过结果（级联跳过下游）。
                skipped_roles.add(role_name)
                skip = skip_result(stage_id, role_name, failed_deps)
                results_by_role[role_name] = skip
                await self._emit_done(stage_id, role_name, skip, skipped=True)
            else:
                run_roles.append(role_name)

        if run_roles:
            await self._progress.spawned(
                total=len(run_roles),
                specs=run_roles,
                stage=stage_id,
                message=f"阶段 {stage_id}：并行启动 {len(run_roles)} 个子 agent（{', '.join(run_roles)}）",
            )
        stage_tasks = [
            _run_one(role_name, self._build_run(task_map[role_name], previous_outputs))
            for role_name in run_roles
        ]
        stage_results = await asyncio.gather(*stage_tasks, return_exceptions=True)
        for role_name, result in zip(run_roles, stage_results, strict=True):
            results_by_role[role_name] = coerce_result(stage_id, role_name, result)
        return [results_by_role[role_name] for role_name in task_roles]

    async def _emit_done(
        self, stage_id: int, role_name: str, result: SubAgentResult, *, skipped: bool = False
    ) -> None:
        self._done += 1
        if skipped:
            message = f"子 agent {role_name} 因上游失败被跳过（{self._done}/{self._total}）"
        elif result.is_error:
            message = f"子 agent {role_name} 执行失败（{self._done}/{self._total}）"
        else:
            message = f"子 agent {role_name} 已完成（{self._done}/{self._total}）"
        await self._progress.agent_done(
            role=role_name,
            completed=self._done,
            total=self._total,
            stage=stage_id,
            error=result.output if result.is_error and not skipped else "",
            skipped=skipped,
            message=message,
        )

    def _build_run(self, task: AgentTask, previous_outputs: dict[str, str]) -> IsolatedAgentRun:
        definition = self._definition_loader.load_role(task.role)
        allowed_tools = task.allowed_tools or (definition.allowed_tools if definition is not None else [])
        description = (
            definition.description
            if definition is not None and definition.description
            else f"请围绕 {task.role} 角色完成分配的子任务。"
        )
        system_prompt = definition.system_prompt if definition is not None else ""
        model = definition.model if definition is not None else ""
        max_iterations = definition.max_iterations if definition is not None else 10
        dependency_outputs = {
            role_name: previous_outputs[role_name]
            for role_name in task.depends_on
            if role_name in previous_outputs
        }
        return IsolatedAgentRun(
            task=task.model_copy(update={"allowed_tools": allowed_tools}),
            description=description,
            system_prompt=system_prompt,
            model=model,
            max_iterations=max_iterations,
            dependency_outputs=dependency_outputs,
        )

__all__ = ["Orchestrator", "OrchestrationError"]
