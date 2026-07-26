import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bot } from "lucide-react";
import { useLocation, useNavigate, useNavigationType, useParams } from "react-router-dom";

import ConnectionBanner from "@/components/chat/ConnectionBanner";
import EmptySessionState from "@/components/chat/EmptySessionState";
import InputBar from "@/components/chat/InputBar";
import MessageList from "@/components/chat/MessageList";
import MessageSkeleton from "@/components/chat/MessageSkeleton";
import SubAgentPanel from "@/components/chat/SubAgentPanel";
import KnowledgeStatusPill from "@/components/knowledge/KnowledgeStatusPill";
import { agentWs } from "@/lib/websocket";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { useSession } from "@/hooks/useSession";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useAgentStore } from "@/stores/agentStore";
import { useSessionStore } from "@/stores/sessionStore";
import { isRunActive, useSubAgentStore } from "@/stores/subAgentStore";
import type { ChatRunOptions } from "@/types";

export default function Session() {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const navigationType = useNavigationType();
  const initialPromptSent = useRef(false);
  const sessionId = id ?? "";
  const { messages, status, streamingText, streamingReasoning, sendMessage } = useSession(sessionId);
  useWebSocket(sessionId);

  const sessions = useSessionStore((state) => state.sessions);
  const currentSessionId = useSessionStore((state) => state.currentSessionId);
  const abortRun = useSessionStore((state) => state.abortRun);
  const connectionState = useSessionStore((state) => state.connectionState);
  const hydrating = useSessionStore((state) => state.hydrating);
  const currentModel = useAgentStore((state) => state.currentModel);
  const currentProviderId = useAgentStore((state) => state.currentProviderId);
  const providers = useAgentStore((state) => state.providers);
  const workspace = useAgentStore((state) => state.workspace);

  // 面板两种打开方式:hover 按钮=临时预览(划走即收),点击=固定打开。
  const [panelPinned, setPanelPinned] = useState(false);
  const [panelPeek, setPanelPeek] = useState(false);
  const peekTimer = useRef<number | null>(null);
  const openPeek = useCallback(() => {
    if (peekTimer.current) window.clearTimeout(peekTimer.current);
    setPanelPeek(true);
  }, []);
  const closePeek = useCallback(() => {
    if (peekTimer.current) window.clearTimeout(peekTimer.current);
    peekTimer.current = window.setTimeout(() => setPanelPeek(false), 200);
  }, []);
  const panelVisible = panelPinned || panelPeek;

  const subAgentRuns = useSubAgentStore((state) => state.runs);
  const lastRunId = useSubAgentStore((state) => state.lastRunId);
  const { runCount, activeAgentCount } = useMemo(() => {
    const sessionRuns = Object.values(subAgentRuns).filter((run) => run.sessionId === sessionId);
    return {
      runCount: sessionRuns.length,
      activeAgentCount: sessionRuns.filter(isRunActive).length,
    };
  }, [subAgentRuns, sessionId]);

  useEffect(() => {
    // 首次出现本会话的子 agent 运行时自动固定面板，让编排过程"开箱可见"。
    if (lastRunId.startsWith(`${sessionId}:`)) setPanelPinned(true);
  }, [lastRunId, sessionId]);

  const activeSession = sessions.find((item) => item.id === sessionId) ?? sessions.find((item) => item.id === currentSessionId);
  const sessionTitle = activeSession?.title.trim() || "新线程";
  useDocumentTitle(sessionTitle);
  const workspaceName = (workspace || activeSession?.workspace || "").split(/[/\\]/).filter(Boolean).pop();
  const currentProvider = providers.find((provider) => provider.id === currentProviderId);
  const modelLabel = [currentProvider?.name, currentModel].filter(Boolean).join(" · ");
  const hasMessages = Boolean(messages.length || streamingText || streamingReasoning);
  const suggestionsEnabled = Boolean(
    currentProviderId && currentModel && !["thinking", "tool_calling", "compacting", "waiting_approval"].includes(status),
  );

  const sendInSession = useCallback(
    (text: string, options?: ChatRunOptions) =>
      sendMessage(text, { ...options, sessionId } as ChatRunOptions & { sessionId: string }),
    [sendMessage, sessionId],
  );

  useEffect(() => {
    initialPromptSent.current = false;
  }, [sessionId]);

  useEffect(() => {
    const state = location.state as ({ initialPrompt?: string } & ChatRunOptions) | null;
    const prompt = state?.initialPrompt?.trim();
    // 仅在应用内 PUSH 跳转（如首页发起新对话）时自动发送首条消息。
    // 刷新 / 前进后退是 POP，浏览器会从 history.state 恢复 location.state，
    // 必须在此拦住，否则刷新会反复自动重发首条消息。
    if (!sessionId || !prompt || navigationType !== "PUSH" || initialPromptSent.current) return;
    initialPromptSent.current = true;
    void (async () => {
      await sendInSession(prompt, { thinking: state?.thinking, thinkingLevel: state?.thinkingLevel });
      navigate(`/session/${sessionId}`, { replace: true, state: null });
    })();
  }, [location.state, navigate, navigationType, sendInSession, sessionId]);

  return (
    <div className="relative flex h-full min-h-0 flex-col bg-[var(--as-bg)]">
      <header className="grid h-12 shrink-0 grid-cols-[160px_1fr_220px] items-center border-b border-[var(--as-border)] px-5">
        <div className="text-xs text-[var(--as-text-subtle)]">{workspaceName ? `项目：${workspaceName}` : ""}</div>
        <div className="max-w-[420px] justify-self-center truncate text-sm font-medium text-[var(--as-text)]" title={sessionTitle}>
          {sessionTitle}
        </div>
        <div className="flex justify-self-end gap-2">
          <button
            type="button"
            onClick={() => setPanelPinned((value) => !value)}
            onMouseEnter={openPeek}
            onMouseLeave={closePeek}
            className={`relative flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] transition ${
              panelPinned
                ? "border-[var(--as-accent)] bg-[var(--as-surface)] text-[var(--as-accent-soft)]"
                : "border-[var(--as-border-strong)] bg-[var(--as-surface)] text-[var(--as-text-secondary)] hover:border-[var(--as-accent)] hover:text-[var(--as-accent-soft)]"
            }`}
            title="子 Agent 面板（悬停预览，点击固定）"
          >
            <Bot size={13} />
            子 Agent
            {runCount ? (
              <span
                className={`ml-0.5 rounded px-1 font-mono text-[10px] ${
                  activeAgentCount
                    ? "animate-pulse bg-[var(--as-thinking-soft)] text-[var(--as-thinking)]"
                    : "bg-[var(--as-surface-low)] text-[var(--as-text-subtle)]"
                }`}
              >
                {runCount}
              </span>
            ) : null}
          </button>
          <KnowledgeStatusPill />
          {modelLabel ? (
            <span className="rounded-md border border-[var(--as-border-strong)] bg-[var(--as-surface)] px-2.5 py-1 font-mono text-[11px] text-[var(--as-text-secondary)]">
              {modelLabel}
            </span>
          ) : null}
        </div>
      </header>

      {sessionId && connectionState !== "connected" ? (
        <ConnectionBanner state={connectionState} onReconnect={() => void agentWs.connect(sessionId)} />
      ) : null}

      <div className="flex min-h-0 flex-1">
        <div className="relative flex min-h-0 flex-1 flex-col">
          {hasMessages ? (
            <MessageList messages={messages} status={status} streamingText={streamingText} streamingReasoning={streamingReasoning} />
          ) : hydrating ? (
            // 会话详情拉取中：渲消息骨架，避免刷新已有会话时先闪一屏空状态建议卡。
            <MessageSkeleton />
          ) : (
            <EmptySessionState
              configured={Boolean(currentProviderId && currentModel)}
              enabled={suggestionsEnabled}
              onPick={(prompt) => void sendInSession(prompt)}
            />
          )}
          <div className="absolute bottom-10 left-0 right-0 px-6">
            <InputBar status={status} onSend={(text, options) => void sendInSession(text, options)} onAbort={abortRun} compact />
          </div>
        </div>
        <div
          onMouseEnter={panelPinned ? undefined : openPeek}
          onMouseLeave={panelPinned ? undefined : closePeek}
          className={`min-h-0 shrink-0 overflow-hidden transition-all duration-200 ease-out ${
            panelVisible ? "w-[320px] opacity-100" : "w-0 opacity-0"
          }`}
        >
          <SubAgentPanel
            sessionId={sessionId}
            onClose={() => {
              setPanelPinned(false);
              setPanelPeek(false);
            }}
          />
        </div>
      </div>
    </div>
  );
}
