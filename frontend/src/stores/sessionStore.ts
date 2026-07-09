import { create } from "zustand";
import { api } from "@/lib/api-client";
import { supportsThinking } from "@/lib/model-capabilities";
import { deriveSessionTitle, mergeSessionMeta, mergeSessionsMeta, removeSessionMeta, saveSessionMeta, summarizeSessionTitle } from "@/lib/session-meta";
import { mapFileDiffs } from "@/lib/tool-diffs";
import { agentWs } from "@/lib/websocket";
import { dropPendingApproval, mergePendingApprovals } from "@/lib/ws-approvals";
import { useAgentStore } from "@/stores/agentStore";
import { useKnowledgeStore } from "@/stores/knowledgeStore";
import type { AgentStatus, ChatRunOptions, Message, Session, ToolCall, ToolResult } from "@/types";
export type ConnectionState = "connected" | "reconnecting" | "disconnected";
interface SessionState {
  sessions: Session[];
  currentSessionId: string | null;
  messages: Message[];
  status: AgentStatus;
  streamingText: string;
  streamingReasoning: string;
  pendingApprovals: ToolCall[];
  lastError: string;
  connectionState: ConnectionState;
  loadSessions: () => Promise<void>;
  createSession: (model: string, providerId?: string, title?: string) => Promise<string>;
  startDraftSession: () => void;
  selectSession: (id: string) => void;
  deleteSession: (id: string) => Promise<void>;
  sendMessage: (text: string, options?: ChatRunOptions) => Promise<void>;
  addMessage: (msg: Message) => void;
  appendStreamText: (text: string) => void;
  appendStreamReasoning: (text: string) => void;
  setStatus: (status: AgentStatus) => void;
  setLastError: (message: string) => void;
  setConnectionState: (state: ConnectionState) => void;
  resync: (sessionId: string) => Promise<void>;
  clearStreamingText: () => void;
  clearStreamingReasoning: () => void;
  abortRun: () => void;
  addPendingApprovals: (calls: ToolCall[]) => void;
  removePendingApproval: (toolCallId: string) => void;
  clearPendingApprovals: () => void;
  respondToApproval: (toolCallId: string, approved: boolean) => void;
  updateSessionTitle: (id: string, title: string) => void;
}
const nextId = () => `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
const sendFailureMessage = "发送失败，消息没有进入后端运行。请刷新页面后重试。";
const asRecord = (value: unknown): Record<string, unknown> => (typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {});
const statuses = ["idle", "thinking", "compacting", "tool_calling", "waiting_approval", "done", "error"];
const messageKinds = ["user_request", "summary", "runtime_guard", "runtime_context", "skill_context", "memory_context"];
const asStatus = (value: unknown): AgentStatus => (typeof value === "string" && statuses.includes(value) ? (value as AgentStatus) : "idle");
// WS 错误归一化：后端 error 事件带 message 字符串；lib/websocket.ts 的 socket.onerror 会 emit 原生 Event（无 message），避免把 undefined 当错误文本。
export const errorText = (payload: unknown): string => {
  const message = (payload as { message?: unknown } | null)?.message;
  return typeof message === "string" && message ? message : "连接错误";
};
const patchSession = (sessions: Session[], id: string, patch: Partial<Pick<Session, "title" | "workspace">>): Session[] =>
  sessions.map((session) => (session.id === id ? { ...session, ...patch } : session));
const mapToolCall = (value: unknown): ToolCall => {
  const item = asRecord(value);
  return { id: String(item.id ?? nextId()), name: String(item.name ?? ""), arguments: asRecord(item.arguments) };
};
const mapToolResult = (value: unknown): ToolResult => {
  const item = asRecord(value);
  const diffs = mapFileDiffs(item.diffs);
  return {
    toolCallId: String(item.toolCallId ?? item.tool_call_id ?? ""),
    output: String(item.output ?? ""),
    isError: Boolean(item.isError ?? item.is_error),
    ...(diffs.length ? { diffs } : {}),
  };
};
const mapMessage = (value: unknown): Message => {
  const item = asRecord(value);
  const role = String(item.role ?? "assistant");
  return {
    id: String(item.id ?? nextId()),
    role: ["user", "assistant", "system", "tool"].includes(role) ? (role as Message["role"]) : "assistant",
    kind: typeof item.kind === "string" && messageKinds.includes(item.kind) ? (item.kind as Message["kind"]) : undefined,
    ephemeral: typeof item.ephemeral === "boolean" ? item.ephemeral : undefined,
    content: String(item.content ?? ""),
    reasoningContent: String(item.reasoningContent ?? item.reasoning_content ?? "") || undefined,
    reasoningDurationMs: Number(item.reasoningDurationMs ?? item.reasoning_duration_ms) || undefined,
    toolCalls: Array.isArray(item.toolCalls) ? item.toolCalls.map(mapToolCall) : Array.isArray(item.tool_calls) ? item.tool_calls.map(mapToolCall) : undefined,
    toolResults: Array.isArray(item.toolResults) ? item.toolResults.map(mapToolResult) : Array.isArray(item.tool_results) ? item.tool_results.map(mapToolResult) : undefined,
    timestamp: String(item.timestamp ?? new Date().toISOString()),
  };
};
const validateWorkspaceForBrowser = async (workspace: string | null): Promise<string> => {
  const path = workspace?.trim() ?? "";
  if (!path || window.electronAPI) return path;
  const validation = await api.validateWorkspace(path);
  if (validation.ok) return validation.path || path;
  useAgentStore.getState().openFolder();
  throw new Error(validation.message || "当前工作区不可用");
};
export const useSessionStore = create<SessionState>((set, get) => ({
  sessions: [],
  currentSessionId: null,
  messages: [],
  status: "idle",
  streamingText: "",
  streamingReasoning: "",
  pendingApprovals: [],
  lastError: "",
  connectionState: "connected",
  loadSessions: async () => {
    try {
      const sessions = mergeSessionsMeta(await api.listSessions());
      const hasCurrent = get().currentSessionId && sessions.some((item) => item.id === get().currentSessionId);
      set({ sessions, currentSessionId: hasCurrent ? get().currentSessionId : null });
    } catch (error) {
      console.error("loadSessions failed", error);
    }
  },
  createSession: async (model: string, providerId?: string, title?: string) => {
    const { workspace } = useAgentStore.getState();
    const nextTitle = summarizeSessionTitle(title ?? "");
    const safeWorkspace = await validateWorkspaceForBrowser(workspace);
    const session = await api.createSession({ model, provider_id: providerId, workspace: safeWorkspace, title: nextTitle });
    if (safeWorkspace || nextTitle) saveSessionMeta(session.id, { workspace: safeWorkspace, title: nextTitle });
    const nextSession = mergeSessionMeta(session);
    set((state) => ({
      sessions: [nextSession, ...state.sessions],
      currentSessionId: nextSession.id,
      messages: [],
      streamingText: "",
      streamingReasoning: "",
      pendingApprovals: [],
      status: "idle",
      lastError: "",
    }));
    return nextSession.id;
  },
  startDraftSession: () => set({ currentSessionId: null, messages: [], streamingText: "", streamingReasoning: "", pendingApprovals: [], status: "idle", lastError: "" }),
  selectSession: (id: string) => {
    set({ currentSessionId: id, messages: [], streamingText: "", streamingReasoning: "", pendingApprovals: [], status: "idle", lastError: "" });
    void (async () => {
      try {
        const detail = asRecord(await api.getSession(id));
        const messages = Array.isArray(detail.messages) ? detail.messages.map(mapMessage) : [];
        const currentSession = get().sessions.find((session) => session.id === id);
        const backendTitle = String(detail.title ?? "").trim();
        const localTitle = currentSession?.title.trim() ?? "";
        const derivedTitle = deriveSessionTitle(messages);
        const nextTitle = backendTitle || localTitle || derivedTitle;
        const nextWorkspace = String(detail.workspace ?? "").trim() || currentSession?.workspace || "";
        if (nextTitle || nextWorkspace) saveSessionMeta(id, { title: nextTitle, workspace: nextWorkspace });
        if (nextTitle && !backendTitle) get().updateSessionTitle(id, nextTitle);
        if (get().currentSessionId !== id) return;
        set((state) => ({
          messages,
          status: asStatus(detail.status),
          sessions: patchSession(state.sessions, id, { title: nextTitle, workspace: nextWorkspace }),
        }));
      } catch (error) {
        console.error("selectSession failed", error);
        set({ status: "error" });
      }
    })();
  },
  deleteSession: async (id: string) => {
    await api.deleteSession(id);
    removeSessionMeta(id);
    const wasCurrent = get().currentSessionId === id;
    set((state) => {
      const sessions = state.sessions.filter((item) => item.id !== id);
      return {
        sessions,
        currentSessionId: wasCurrent ? null : state.currentSessionId,
        messages: wasCurrent ? [] : state.messages,
        streamingText: wasCurrent ? "" : state.streamingText,
        streamingReasoning: wasCurrent ? "" : state.streamingReasoning,
        pendingApprovals: wasCurrent ? [] : state.pendingApprovals,
        status: wasCurrent ? "idle" : state.status,
        lastError: wasCurrent ? "" : state.lastError,
      };
    });
  },
  sendMessage: async (text: string, options?: ChatRunOptions) => {
    const content = text.trim();
    if (!content) return;
    const runOptions = options as (ChatRunOptions & { sessionId?: string }) | undefined;
    let agentState = useAgentStore.getState();
    if (!agentState.currentModel || !agentState.currentProviderId || !agentState.providers.length) {
      await agentState.loadProviders();
      agentState = useAgentStore.getState();
    }
    const { currentModel, currentProviderId, providers, workspace, permissionMode, thinkingLevel } = agentState;
    const knowledge = useKnowledgeStore.getState();
    const sessionId = runOptions?.sessionId ?? get().currentSessionId;
    const provider = providers.find((item) => item.id === currentProviderId);
    if (!sessionId) return;
    if (!provider || !currentModel) {
      console.error("send skipped: provider or model is not ready");
      set({ status: "error" });
      return;
    }
    const userMsg: Message = {
      id: nextId(),
      role: "user",
      content,
      timestamp: new Date().toISOString(),
    };
    set((state) => ({ messages: [...state.messages, userMsg], streamingText: "", streamingReasoning: "", pendingApprovals: [], status: "thinking", lastError: "" }));
    const session = get().sessions.find((item) => item.id === sessionId);
    if (!session?.title.trim()) get().updateSessionTitle(sessionId, summarizeSessionTitle(content));
    if (workspace && workspace !== session?.workspace) {
      saveSessionMeta(sessionId, { workspace });
      set((state) => ({ sessions: patchSession(state.sessions, sessionId, { workspace }) }));
    }
    try {
      await agentWs.connect(sessionId);
      const selectedThinking = runOptions?.thinkingLevel ?? (runOptions?.thinking ? "high" : thinkingLevel);
      const selectedMode = runOptions?.mode ?? knowledge.mode;
      const selectedKbId = runOptions?.knowledgeBaseId ?? knowledge.currentKbId;
      const knowledgeEnabled = selectedMode === "knowledge" && Boolean(selectedKbId);
      const runPayload: { type: string; [key: string]: unknown } = {
        type: "run",
        message: content,
        model: currentModel,
        provider_id: currentProviderId ?? undefined,
        workspace: workspace ?? undefined,
        permission_mode: permissionMode,
        mode: knowledgeEnabled ? "knowledge" : "direct",
        knowledge_base_id: knowledgeEnabled ? selectedKbId : undefined,
        thinking: supportsThinking(provider, currentModel) && selectedThinking === "high",
      };
      if (!agentWs.send(runPayload)) {
        await agentWs.connect(sessionId);
        if (!agentWs.send(runPayload)) throw new Error("WebSocket is not connected");
      }
    } catch (error) {
      console.error("send failed:", error);
      // 融合 F3：发送失败统一经 lastError 呈现（MessageList 的“运行出错”横幅消费），沿用 HEAD 更明确的文案（消息未进入后端）。
      set({ status: "error", lastError: sendFailureMessage });
    }
  },
  addMessage: (msg: Message) => set((state) => ({ messages: [...state.messages, msg] })),
  appendStreamText: (text: string) => set((state) => ({ streamingText: `${state.streamingText}${text}` })),
  appendStreamReasoning: (text: string) => set((state) => ({ streamingReasoning: `${state.streamingReasoning}${text}` })),
  setStatus: (status: AgentStatus) => set({ status }),
  setLastError: (message: string) => set({ lastError: message }),
  setConnectionState: (connectionState: ConnectionState) => set({ connectionState }),
  resync: async (sessionId: string) => {
    // 非破坏性补偿：断线重连后重新拉取会话，成功且非空才替换 messages/status；
    // 失败或空结果均保留旧 messages（绝不清空）；会话已切换则丢弃结果，避免写脏当前会话。
    if (get().currentSessionId !== sessionId) return;
    try {
      const detail = asRecord(await api.getSession(sessionId));
      if (get().currentSessionId !== sessionId) return;
      const nextMessages = Array.isArray(detail.messages) ? detail.messages.map(mapMessage) : [];
      set((state) => ({
        messages: nextMessages.length ? nextMessages : state.messages,
        status: asStatus(detail.status),
      }));
    } catch (error) {
      console.error("resync failed", error);
    }
  },
  clearStreamingText: () => set({ streamingText: "" }),
  clearStreamingReasoning: () => set({ streamingReasoning: "" }),
  abortRun: () => {
    if (!agentWs.send({ type: "abort" })) console.warn("abort skipped: websocket not connected");
    const { streamingText, streamingReasoning, status } = get();
    const content = streamingText || (["thinking", "compacting", "tool_calling", "waiting_approval"].includes(status) ? (status === "tool_calling" ? "已停止，工具调用已中断。" : "已停止，当前任务已中断。") : "");
    if (!content && !streamingReasoning) { set({ status: "idle" }); return; }
    set((state) => ({ messages: [...state.messages, { id: nextId(), role: "assistant", content, reasoningContent: streamingReasoning || undefined, timestamp: new Date().toISOString() }], status: "done", streamingText: "", streamingReasoning: "" }));
  },
  addPendingApprovals: (calls: ToolCall[]) => set((state) => ({ pendingApprovals: mergePendingApprovals(state.pendingApprovals, calls) })),
  removePendingApproval: (toolCallId: string) => set((state) => ({ pendingApprovals: dropPendingApproval(state.pendingApprovals, toolCallId) })),
  clearPendingApprovals: () => set((state) => (state.pendingApprovals.length ? { pendingApprovals: [] } : state)),
  respondToApproval: (toolCallId: string, approved: boolean) => {
    if (!agentWs.send({ type: approved ? "tool_approve" : "tool_reject", tool_call_id: toolCallId })) {
      console.warn("approval decision skipped: websocket not connected");
      return;
    }
    set((state) => ({ pendingApprovals: dropPendingApproval(state.pendingApprovals, toolCallId) }));
  },
  updateSessionTitle: (id: string, title: string) => {
    const nextTitle = summarizeSessionTitle(title);
    if (!nextTitle) return;
    saveSessionMeta(id, { title: nextTitle });
    set((state) => ({ sessions: patchSession(state.sessions, id, { title: nextTitle }) }));
    void api.updateSessionTitle(id, nextTitle).then((saved) => {
      const savedTitle = saved.title.trim() || nextTitle;
      saveSessionMeta(id, { title: savedTitle });
      set((state) => ({ sessions: patchSession(state.sessions, id, { title: savedTitle }) }));
    }).catch((error) => console.error("updateSessionTitle failed", error));
  },
}));
