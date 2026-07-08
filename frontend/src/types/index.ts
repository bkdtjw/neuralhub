export interface Message {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  reasoningContent?: string;
  reasoningDurationMs?: number;
  toolCalls?: ToolCall[];
  toolResults?: ToolResult[];
  timestamp: string;
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export type DiffChangeType = "create" | "modify" | "delete";

export interface FileDiff {
  path: string;
  unifiedDiff: string;
  changeType: DiffChangeType;
}

export interface ToolResult {
  toolCallId: string;
  output: string;
  isError: boolean;
  diffs?: FileDiff[];
}

export type AgentStatus = "idle" | "thinking" | "compacting" | "tool_calling" | "waiting_approval" | "done" | "error";

export interface Session {
  id: string;
  model: string;
  providerId?: string;
  status: AgentStatus;
  createdAt: string;
  messageCount: number;
  title: string;
  workspace: string;
}

export interface Provider {
  id: string;
  name: string;
  providerType: string;
  baseUrl: string;
  apiKeyPreview: string;
  defaultModel: string;
  availableModels: string[];
  isDefault: boolean;
  enabled: boolean;
}

export interface WorkspaceEntry {
  name: string;
  path: string;
  isDirectory: boolean;
  isProject: boolean;
}

export interface WorkspaceCrumb {
  name: string;
  path: string;
}

export interface WorkspaceList {
  root: string;
  path: string;
  parent?: string | null;
  breadcrumbs: WorkspaceCrumb[];
  entries: WorkspaceEntry[];
  truncated: boolean;
}

export interface WorkspaceValidation {
  ok: boolean;
  path: string;
  isProject: boolean;
  message: string;
}

export type ThinkingLevel = "low" | "medium" | "high";

export interface ChatRunOptions { thinking?: boolean; thinkingLevel?: ThinkingLevel; mode?: "direct" | "project" | "knowledge"; knowledgeBaseId?: string; }

export type MetricName =
  | "llm_calls"
  | "llm_errors"
  | "llm_prompt_tokens"
  | "llm_completion_tokens"
  | "llm_cached_prompt_tokens"
  | "tool_calls"
  | "tool_errors"
  | "task_triggers"
  | "task_successes"
  | "task_failures"
  | "feishu_messages"
  | "feishu_replies"
  | "agent_runs";

export interface MetricSeries {
  total: number;
  daily: Record<string, number>;
}

export interface MetricsSummary {
  periodDays: number;
  metrics: Record<MetricName, MetricSeries>;
}

export interface MetricDetail {
  name: string;
  total: number;
  daily: Record<string, number>;
}

export interface LatencyStat {
  name: string;
  count: number;
  p50_ms: number;
  p95_ms: number;
  max_ms: number;
}

export interface LatencySummary {
  latencies: Record<string, LatencyStat>;
}

export type LogLevel = "debug" | "info" | "warning" | "error";

export interface LogEntry {
  timestamp: string;
  level: LogLevel;
  event: string;
  traceId: string;
  sessionId: string;
  workerId: string;
  component: string;
  extra: Record<string, unknown>;
}

export interface LogSearchParams {
  traceId?: string;
  sessionId?: string;
  level?: LogLevel | "";
  event?: string;
  component?: string;
  workerId?: string;
  errorCode?: string;
  limit?: number;
  minutes?: number;
}

export interface LogSearchResult {
  count: number;
  logs: LogEntry[];
}

export interface TraceResult {
  traceId: string;
  events: LogEntry[];
}

export interface TraceSpan {
  traceId: string;
  spanId: string;
  parentSpanId: string;
  name: string;
  status: "success" | "error";
  startTime: string;
  endTime: string;
  durationMs: number;
  component: string;
  attributes: Record<string, unknown>;
}

export interface TraceSpanResult {
  traceId: string;
  spans: TraceSpan[];
}

export type WsIncoming =
  | { type: "status"; status: AgentStatus }
  | { type: "message"; content: string; reasoningContent?: string; toolCalls?: ToolCall[] }
  | { type: "tool_call"; id: string; name: string; arguments: Record<string, unknown> }
  | { type: "tool_result"; toolCallId: string; output: string; isError: boolean; diffs?: FileDiff[] }
  | { type: "security_reject"; toolCallId: string; output: string; isError: boolean; diffs?: FileDiff[] }
  | { type: "tool_approval_required"; toolCalls: ToolCall[]; timeoutSeconds?: number }
  | { type: "text"; content: string }
  | { type: "reasoning"; content: string }
  | { type: "done"; message: Message }
  | { type: "error"; message: string }
  | { type: "ignored"; raw?: Record<string, unknown> };
