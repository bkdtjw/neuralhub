import { useEffect, useRef } from "react";

import { agentWs } from "@/lib/websocket";
import { createConnectionHandlers } from "@/hooks/ws-connection";
import { createReasoningTracker } from "@/hooks/ws-reasoning";
import { errorText, useSessionStore } from "@/stores/sessionStore";
import type { ToolCall, ToolResult, WsIncoming } from "@/types";

const makeId = () => `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
const TOOL_RESULT_TIMEOUT_MS = 90_000;

export function useWebSocket(sessionId: string) {
  const pendingToolCalls = useRef<ToolCall[]>([]);
  const pendingToolResults = useRef<ToolResult[]>([]);
  const pendingContent = useRef("");
  const pendingReasoning = useRef("");
  const reasoning = useRef(createReasoningTracker());
  const pendingCallsFromMessage = useRef(false);
  const waitingForToolResults = useRef(false);
  const toolResultTimeout = useRef<number | null>(null);
  const approvalPaused = useRef(false);

  useEffect(() => {
    if (!sessionId) return;

    const clearToolResultTimeout = () => {
      if (toolResultTimeout.current === null) return;
      window.clearTimeout(toolResultTimeout.current);
      toolResultTimeout.current = null;
    };

    const orderedResultsForCalls = () => {
      const byId = new Map(
        pendingToolResults.current
          .filter((result) => result.toolCallId)
          .map((result) => [result.toolCallId, result] as const),
      );
      return pendingToolCalls.current
        .map((call, index) => (call.id ? byId.get(call.id) : pendingToolResults.current[index]))
        .filter((result): result is ToolResult => Boolean(result));
    };

    const allPendingCallsResolved = () => {
      if (!pendingToolCalls.current.length) return false;
      const resolvedIds = new Set(
        pendingToolResults.current
          .map((result) => result.toolCallId)
          .filter(Boolean),
      );
      return pendingToolCalls.current.every((call, index) => {
        if (call.id) return resolvedIds.has(call.id);
        return Boolean(pendingToolResults.current[index]);
      });
    };

    const flushPendingMessage = () => {
      const content = pendingContent.current;
      const calls = pendingToolCalls.current;
      const results = orderedResultsForCalls();
      if (!content && !calls.length) return;
      clearToolResultTimeout();
      useSessionStore.getState().addMessage({
        id: makeId(),
        role: "assistant",
        content,
        reasoningContent: pendingReasoning.current || undefined,
        reasoningDurationMs: pendingReasoning.current ? reasoning.current.duration() : undefined,
        toolCalls: calls.length ? [...calls] : undefined,
        toolResults: results.length ? [...results] : undefined,
        timestamp: new Date().toISOString(),
      });
      pendingContent.current = "";
      pendingReasoning.current = "";
      pendingToolCalls.current = [];
      pendingToolResults.current = [];
      pendingCallsFromMessage.current = false;
      waitingForToolResults.current = false;
      reasoning.current.reset();
    };

    const startToolResultTimeout = () => {
      if (!waitingForToolResults.current || !pendingToolCalls.current.length) return;
      clearToolResultTimeout();
      toolResultTimeout.current = window.setTimeout(() => {
        const resolvedIds = new Set(
          pendingToolResults.current
            .map((result) => result.toolCallId)
            .filter(Boolean),
        );
        const missingResults = pendingToolCalls.current
          .filter((call, index) => (call.id ? !resolvedIds.has(call.id) : !pendingToolResults.current[index]))
          .map((call) => ({
            toolCallId: call.id,
            output: "工具执行超时，未收到结果事件。",
            isError: true,
          }));
        pendingToolResults.current = [...pendingToolResults.current, ...missingResults];
        flushPendingMessage();
        useSessionStore.getState().setStatus("error");
      }, TOOL_RESULT_TIMEOUT_MS);
    };

    const finishIfToolResultsComplete = () => {
      if (!waitingForToolResults.current) return;
      if (allPendingCallsResolved()) {
        flushPendingMessage();
        return;
      }
      startToolResultTimeout();
    };

    const upsertToolResult = (result: ToolResult) => {
      const existingIndex = pendingToolResults.current.findIndex(
        (item) => item.toolCallId && item.toolCallId === result.toolCallId,
      );
      if (existingIndex >= 0) {
        pendingToolResults.current = pendingToolResults.current.map((item, index) =>
          index === existingIndex ? result : item,
        );
        return;
      }
      pendingToolResults.current = [...pendingToolResults.current, result];
    };

    const onStatus = (payload: unknown) => {
      const p = payload as Extract<WsIncoming, { type: "status" }>;
      // 审批期间后端给 300s 合法等待：暂停前端 90s 工具结果定时器；离开审批（回到 tool_calling）再按需重启。
      if (p.status === "waiting_approval") {
        approvalPaused.current = true;
        clearToolResultTimeout();
      } else if (approvalPaused.current) {
        approvalPaused.current = false;
        startToolResultTimeout();
      }
      useSessionStore.getState().setStatus(p.status);
    };

    const onText = (payload: unknown) => {
      const p = payload as Extract<WsIncoming, { type: "text" }>;
      reasoning.current.finish();
      useSessionStore.getState().appendStreamText(p.content);
    };

    const onReasoning = (payload: unknown) => {
      const p = payload as Extract<WsIncoming, { type: "reasoning" }>;
      reasoning.current.start();
      useSessionStore.getState().appendStreamReasoning(p.content);
    };

    const onToolApprovalRequired = (payload: unknown) => {
      const p = payload as Extract<WsIncoming, { type: "tool_approval_required" }>;
      approvalPaused.current = true;
      clearToolResultTimeout();
      useSessionStore.getState().addPendingApprovals(p.toolCalls);
    };

    const onMessage = (payload: unknown) => {
      const p = payload as Extract<WsIncoming, { type: "message" }>;
      const state = useSessionStore.getState();

      if (p.toolCalls && p.toolCalls.length > 0) {
        pendingContent.current = p.content || "";
        pendingReasoning.current = p.reasoningContent || state.streamingReasoning || "";
        pendingToolCalls.current = p.toolCalls.map((call) => ({
          id: call.id || makeId(),
          name: call.name,
          arguments: call.arguments,
        }));
        const callIds = new Set(pendingToolCalls.current.map((call) => call.id).filter(Boolean));
        pendingToolResults.current = pendingToolResults.current.filter((result) =>
          result.toolCallId ? callIds.has(result.toolCallId) : false,
        );
        pendingCallsFromMessage.current = true;
        waitingForToolResults.current = true;
        state.clearStreamingText();
        state.clearStreamingReasoning();
        finishIfToolResultsComplete();
        return;
      }

      if (waitingForToolResults.current) {
        flushPendingMessage();
      } else {
        pendingToolResults.current = [];
      }
      state.clearStreamingText();
      state.clearStreamingReasoning();
      state.addMessage({
        id: makeId(),
        role: "assistant",
        content: p.content || state.streamingText,
        reasoningContent: p.reasoningContent || state.streamingReasoning || undefined,
        reasoningDurationMs: p.reasoningContent || state.streamingReasoning ? reasoning.current.duration() : undefined,
        timestamp: new Date().toISOString(),
      });
      reasoning.current.reset();
    };

    const onToolCall = (payload: unknown) => {
      const p = payload as Extract<WsIncoming, { type: "tool_call" }>;
      if (pendingCallsFromMessage.current) return;

      const exists = pendingToolCalls.current.some(
        (call) => call.id === p.id || (call.name === p.name && JSON.stringify(call.arguments) === JSON.stringify(p.arguments)),
      );
      if (!exists) {
        pendingToolCalls.current.push({
          id: p.id || makeId(),
          name: p.name,
          arguments: p.arguments,
        });
      }
      waitingForToolResults.current = pendingToolCalls.current.length > 0;
      finishIfToolResultsComplete();
    };

    const onToolResult = (payload: unknown) => {
      const p = payload as Extract<WsIncoming, { type: "tool_result" | "security_reject" }>;
      const nextCall =
        pendingToolCalls.current.find((call) => call.id === p.toolCallId) ??
        pendingToolCalls.current[pendingToolResults.current.length];
      upsertToolResult({
        toolCallId: p.toolCallId || nextCall?.id || "",
        output: p.output,
        isError: p.isError,
        ...(p.diffs?.length ? { diffs: p.diffs } : {}),
      });
      // 兜底移除：无论用户点击、飞书审批还是后端 300s 超时，收到该工具结果即从待审批列表清掉。
      if (p.toolCallId) useSessionStore.getState().removePendingApproval(p.toolCallId);
      finishIfToolResultsComplete();
    };

    const onDone = () => {
      const state = useSessionStore.getState();
      if (waitingForToolResults.current) flushPendingMessage();
      if (state.streamingText || state.streamingReasoning) {
        state.addMessage({
          id: makeId(),
          role: "assistant",
          content: state.streamingText,
          reasoningContent: state.streamingReasoning || undefined,
          reasoningDurationMs: state.streamingReasoning ? reasoning.current.duration() : undefined,
          timestamp: new Date().toISOString(),
        });
      }
      state.clearStreamingText();
      state.clearStreamingReasoning();
      state.clearPendingApprovals();
      state.setStatus("done");
      approvalPaused.current = false;
      reasoning.current.reset();
    };

    const onError = (payload: unknown) => {
      if (waitingForToolResults.current) flushPendingMessage();
      approvalPaused.current = false;
      const state = useSessionStore.getState();
      state.clearPendingApprovals();
      state.setLastError(errorText(payload));
      state.setStatus("error");
      console.error("WebSocket error:", payload);
    };

    const connection = createConnectionHandlers(sessionId);

    agentWs.connect(sessionId);
    agentWs.on("open", connection.onOpen);
    agentWs.on("close", connection.onClose);
    agentWs.on("give-up", connection.onGiveUp);
    agentWs.on("status", onStatus);
    agentWs.on("text", onText);
    agentWs.on("reasoning", onReasoning);
    agentWs.on("message", onMessage);
    agentWs.on("tool_call", onToolCall);
    agentWs.on("tool_result", onToolResult);
    agentWs.on("security_reject", onToolResult);
    agentWs.on("tool_approval_required", onToolApprovalRequired);
    agentWs.on("done", onDone);
    agentWs.on("error", onError);
    return () => {
      clearToolResultTimeout();
      agentWs.off("open", connection.onOpen);
      agentWs.off("close", connection.onClose);
      agentWs.off("give-up", connection.onGiveUp);
      agentWs.off("status", onStatus);
      agentWs.off("text", onText);
      agentWs.off("reasoning", onReasoning);
      agentWs.off("message", onMessage);
      agentWs.off("tool_call", onToolCall);
      agentWs.off("tool_result", onToolResult);
      agentWs.off("security_reject", onToolResult);
      agentWs.off("tool_approval_required", onToolApprovalRequired);
      agentWs.off("done", onDone);
      agentWs.off("error", onError);
      pendingToolCalls.current = [];
      pendingToolResults.current = [];
      pendingContent.current = "";
      pendingReasoning.current = "";
      reasoning.current.reset();
      pendingCallsFromMessage.current = false;
      waitingForToolResults.current = false;
      approvalPaused.current = false;
      useSessionStore.getState().clearPendingApprovals();
      agentWs.close();
    };
  }, [sessionId]);
}
