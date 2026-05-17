from __future__ import annotations

from typing import TYPE_CHECKING

from backend.common.errors import AgentError
from backend.common.metrics import incr
from backend.common.types import Message

from .agent_loop_support import (
    build_llm_request,
    build_run_logger,
    log_llm_call_end,
    log_tool_result,
    message_fingerprint,
    patch_orphan_tool_calls,
    response_content,
)
from .failure_recovery import ToolFailureRecoveryTracker
from .tool_batching import merge_results, partition_by_side_effect

if TYPE_CHECKING:
    from .agent_loop import AgentLoop


async def run_agent_loop(loop: AgentLoop, user_message: str) -> Message:
    failure_recovery = ToolFailureRecoveryTracker(
        loop._config.max_consecutive_tool_failures
    )
    iteration_count = 0
    _trace_id, _session_id, logger, log_context = build_run_logger(loop._config.session_id)
    with log_context:
        try:
            was_aborted = loop._aborted
            loop._aborted = False
            if was_aborted:
                raise AgentError(code="LOOP_ABORTED", message="Agent loop aborted")
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
                messages = loop._history.raw_messages
                messages[:] = await loop._layered_compressor.check_and_compact(messages)
                messages[:] = await loop._layered_compressor.summarize_and_archive(messages)
                estimated_tokens = loop._token_counter.estimate_messages_tokens(messages)
                estimated_tokens += loop._token_counter.estimate_tools_tokens(tool_definitions)
                if loop._compressor.policy.should_compact(estimated_tokens):
                    loop._set_status("compacting")
                    messages[:] = await loop._compressor.compact(messages)
                    loop._set_status("thinking")
                logger.info("llm_call_start", iteration=iteration_count)
                response = await loop._adapter.complete(
                    build_llm_request(
                        loop._config,
                        loop._history.raw_messages,
                        tool_definitions,
                        skill_loader=loop._skill_loader,
                        memory_index=loop._memory_index,
                        static_skill_messages=loop._static_skill_messages,
                    )
                )
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
                signed_results = [
                    await loop._layered_compressor.process_tool_result(result)
                    for result in signed_results
                ]
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
            logger.exception("agent_run_error", iterations=iteration_count)
            existing_count = len(loop._history)
            patch_orphan_tool_calls(loop._history.raw_messages)
            await loop._history.checkpoint_from(existing_count)
            raise


__all__ = ["run_agent_loop"]
