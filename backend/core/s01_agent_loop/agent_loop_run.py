from __future__ import annotations

from time import monotonic
from typing import TYPE_CHECKING

from backend.common.errors import AgentError
from backend.common.metrics import incr, record_latency_sample
from backend.common.prometheus_metrics import observe_agent_run
from backend.common.tracing import trace_context, trace_span
from backend.common.types import Message

from .agent_loop_guard import AgentLoopGuard
from .agent_loop_support import (
    build_llm_request,
    build_run_logger,
    log_llm_call_end,
    log_tool_result,
    message_fingerprint,
    patch_orphan_tool_calls,
    response_content,
)
from .compaction_writeback import apply_layered_compaction
from .failure_recovery import ToolFailureRecoveryTracker
from .streaming import complete_with_stream
from .tool_batching import merge_results, partition_by_side_effect

if TYPE_CHECKING:
    from .agent_loop import AgentLoop


async def _patch_and_checkpoint(loop: AgentLoop) -> None:
    # 收尾自愈：为末尾“带 tool_calls 无 tool_results 的 assistant”补合成 tool 结果并落盘。
    existing_count = len(loop._history)
    patch_orphan_tool_calls(loop._history.raw_messages)
    await loop._history.checkpoint_from(existing_count)


async def run_agent_loop(loop: AgentLoop, user_message: str) -> Message:
    failure_recovery = ToolFailureRecoveryTracker(
        loop._config.max_consecutive_tool_failures
    )
    loop_guard = AgentLoopGuard(loop._config)
    iteration_count = 0
    run_started = monotonic()
    _trace_id, _session_id, logger, log_context = build_run_logger(loop._config.session_id)
    with trace_context(_trace_id), log_context, trace_span(
        "agent.run",
        {"session_id": _session_id, "model": loop._config.model, "provider": loop._config.provider},
    ) as run_span:
        try:
            # 清零残留中止标志但不抛错：残留标志只可能来自上一次“停止”（上一轮被 task.cancel()
            # 打断或空闲期 abort 会留下 _aborted=True），不应中断本次新任务；在此重抛会让本轮消息
            # 未入历史就误报 LOOP_ABORTED（运行中的中止仍由循环内 loop._aborted 判定 + websocket
            # 的 task.cancel() 覆盖，语义不丢）。
            loop._aborted = False
            loop._ensure_system_message()
            await loop._append_message(Message(role="user", content=user_message))
            logger.info(
                "agent_run_start",
                user_message_length=len(user_message),
                user_message_hash=message_fingerprint(user_message),
            )
            await incr("agent_runs")
            for _ in range(loop._config.max_iterations):
                iteration_count += 1
                loop._set_status("thinking")
                tool_definitions = loop._executor.list_definitions()
                # 差量写回：压缩基于 await 前快照整表覆盖，await 期间并发 run 追加到尾部的
                # 消息会被丢弃。apply_layered_compaction 在每处 await 前取 snapshot_len，写回时
                # 把尾部新增消息接回，保住并发追加的消息（详见 compaction_writeback）。
                messages = loop._history.raw_messages
                await apply_layered_compaction(loop, messages, tool_definitions)
                guard_prompt = loop_guard.prompt_for_iteration(iteration_count)
                if guard_prompt is not None:
                    await loop._append_message(
                        Message(
                            role="user",
                            kind="runtime_guard",
                            ephemeral=True,
                            content=(
                                "<system_directive>\n"
                                f"{guard_prompt.content}\n"
                                "这是系统注入的运行时指令，不是用户的新任务。\n"
                                "</system_directive>"
                            ),
                        )
                    )
                    logger.info(
                        "agent_loop_guard_prompt",
                        iteration=iteration_count,
                        kind=guard_prompt.kind,
                    )
                logger.info("llm_call_start", iteration=iteration_count)
                with trace_span(
                    "llm.call",
                    {
                        "iteration": iteration_count,
                        "model": loop._config.model,
                        "provider": loop._config.provider,
                    },
                ):
                    request = build_llm_request(
                        loop._config,
                        loop._history.raw_messages,
                        tool_definitions,
                        skill_loader=loop._skill_loader,
                        memory_index=loop._memory_index,
                        static_skill_messages=loop._static_skill_messages,
                    )
                    response = await complete_with_stream(loop, request)
                log_llm_call_end(logger, response)
                assistant = Message(
                    content=response_content(response),
                    role="assistant",
                    tool_calls=response.tool_calls or None,
                    provider_metadata=response.provider_metadata,
                )
                await loop._append_message(assistant)
                loop._emit("message", assistant)
                if not response.tool_calls:
                    loop._set_status("done")
                    run_span.set_attribute("iterations", iteration_count)
                    duration_seconds = monotonic() - run_started
                    observe_agent_run("success", duration_seconds)
                    await record_latency_sample("agent_run", int(duration_seconds * 1000))
                    logger.info("agent_run_end", iterations=iteration_count)
                    return assistant
                call_map = {call.id: call for call in response.tool_calls}
                loop._set_status("tool_calling")
                for call in response.tool_calls:
                    logger.info("tool_call_start", tool=call.name, tool_call_id=call.id)
                    loop._emit("tool_call", call)
                allowed_calls, skipped_results = failure_recovery.split_repeated(
                    response.tool_calls
                )
                auth_result = loop._security_gate.authorize(allowed_calls)
                for rejected in auth_result.rejected_results:
                    log_tool_result(logger, call_map.get(rejected.tool_call_id), rejected)
                    loop._emit("security_reject", rejected)
                approved_calls = []
                approval_results = []
                if auth_result.pending_approval:
                    auto_approved, auto_results, human_calls = await loop.review_tool_approvals(
                        auth_result.pending_approval
                    )
                    approved_calls.extend(auto_approved)
                    approval_results.extend(auto_results)
                else:
                    human_calls = []
                if human_calls:
                    loop._set_status("waiting_approval")
                    human_approved, human_results = await loop.wait_tool_approvals(human_calls)
                    approved_calls.extend(human_approved)
                    approval_results.extend(human_results)
                    loop._set_status("tool_calling")
                signed_calls = [
                    *auth_result.signed_calls,
                    *loop._security_gate.force_sign(approved_calls),
                ]
                read_only_calls, write_calls = partition_by_side_effect(
                    signed_calls,
                    tool_definitions,
                )
                read_results = await loop._executor.execute_signed_batch(
                    read_only_calls,
                    loop._security_gate,
                )
                write_results = await loop._executor.execute_signed_serial(
                    write_calls,
                    loop._security_gate,
                )
                signed_results = merge_results(read_results, write_results, signed_calls)
                results = failure_recovery.annotate(
                    [
                        *skipped_results,
                        *auth_result.rejected_results,
                        *approval_results,
                        *signed_results,
                    ],
                    call_map,
                )
                for result in results:
                    log_tool_result(logger, call_map.get(result.tool_call_id), result)
                    loop._emit("tool_result", result)
                await loop._append_message(Message(role="tool", content="", tool_results=results))
                if loop._aborted:
                    raise AgentError(code="LOOP_ABORTED", message="Agent loop aborted")
            raise AgentError(code="LOOP_MAX_ITERATIONS", message="Max iterations exceeded")
        except Exception as exc:
            loop._status = "error"
            loop._emit("error", exc)
            run_span.set_attribute("iterations", iteration_count)
            duration_seconds = monotonic() - run_started
            observe_agent_run("error", duration_seconds)
            await record_latency_sample("agent_run", int(duration_seconds * 1000))
            logger.exception("agent_run_error", iterations=iteration_count)
            await _patch_and_checkpoint(loop)
            raise
        except BaseException:
            # 取消/中断（CancelledError 等）：只做孤儿修补 + checkpoint 后原样重抛，
            # 不重复 emit error/metrics（那是 Exception 分支的事），务必重抛不吞。
            await _patch_and_checkpoint(loop)
            raise
        finally:
            # task.cancel() 抛出的 CancelledError 不经过上面的 except，
            # 必须在 finally 里复位，否则残留标志会误杀下一次 run
            loop._aborted = False


__all__ = ["run_agent_loop"]
