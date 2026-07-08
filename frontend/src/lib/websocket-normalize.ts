import { mapFileDiffs } from "@/lib/tool-diffs";
import type { AgentStatus, Message, ToolCall, WsIncoming } from "@/types";

const asRecord = (value: unknown): Record<string, unknown> =>
  typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};

// 审批工具透传：后端 call.model_dump() 为 snake_case，映射 id/name/arguments。
const mapApprovalToolCall = (value: unknown): ToolCall => {
  const call = asRecord(value);
  return { id: String(call.id ?? ""), name: String(call.name ?? ""), arguments: asRecord(call.arguments) };
};

export const normalizeWsIncoming = (raw: Record<string, unknown>): WsIncoming => {
  const type = String(raw.type ?? "error");
  if (type === "status") return { type: "status", status: String(raw.status ?? "error") as AgentStatus };
  if (type === "message") {
    const toolCalls = (raw.tool_calls as ToolCall[] | undefined) ?? undefined;
    return { type: "message", content: String(raw.content ?? ""), reasoningContent: String(raw.reasoning_content ?? ""), toolCalls };
  }
  if (type === "tool_call") {
    return {
      type: "tool_call",
      id: String(raw.id ?? ""),
      name: String(raw.name ?? ""),
      arguments: (raw.arguments as Record<string, unknown>) ?? {},
    };
  }
  if (type === "tool_result") {
    return {
      type: "tool_result",
      toolCallId: String(raw.tool_call_id ?? ""),
      output: String(raw.output ?? ""),
      isError: Boolean(raw.is_error),
      diffs: mapFileDiffs(raw.diffs),
    };
  }
  if (type === "security_reject") {
    return {
      type: "security_reject",
      toolCallId: String(raw.tool_call_id ?? ""),
      output: String(raw.output ?? ""),
      isError: Boolean(raw.is_error),
      diffs: mapFileDiffs(raw.diffs),
    };
  }
  if (type === "text") return { type: "text", content: String(raw.content ?? "") };
  if (type === "reasoning") return { type: "reasoning", content: String(raw.content ?? "") };
  if (type === "done") return { type: "done", message: raw.message as Message };
  if (type === "tool_approval_required") {
    const rawCalls = Array.isArray(raw.tool_calls) ? raw.tool_calls : [];
    const timeout = Number(raw.timeout_seconds);
    return {
      type: "tool_approval_required",
      toolCalls: rawCalls.map(mapApprovalToolCall),
      ...(Number.isFinite(timeout) && timeout > 0 ? { timeoutSeconds: timeout } : {}),
    };
  }
  // 兜底中性化：仅后端显式下发的 error 才终止会话；其余未知事件（sub_agent_*、
  // plan_resume_available 等）归一化为 ignored，不误判为 error。
  if (raw.type === "error") return { type: "error", message: String(raw.message ?? "Unknown websocket error") };
  return { type: "ignored", raw };
};
