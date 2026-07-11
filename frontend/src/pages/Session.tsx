import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bot, Code2, Search, WandSparkles, type LucideIcon } from "lucide-react";
import { useLocation, useNavigate, useNavigationType, useParams } from "react-router-dom";

import InputBar from "@/components/chat/InputBar";
import MessageList from "@/components/chat/MessageList";
import SubAgentPanel from "@/components/chat/SubAgentPanel";
import KnowledgeStatusPill from "@/components/knowledge/KnowledgeStatusPill";
import { agentWs } from "@/lib/websocket";
import { useSession } from "@/hooks/useSession";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useAgentStore } from "@/stores/agentStore";
import { useSessionStore } from "@/stores/sessionStore";
import { isRunActive, useSubAgentStore } from "@/stores/subAgentStore";
import type { ChatRunOptions } from "@/types";

const EMPTY_SUGGESTIONS: { icon: LucideIcon; label: string; prompt: string }[] = [
  { icon: Code2, label: "梳理当前项目结构", prompt: "请先阅读当前项目结构，告诉我主要模块和入口文件。" },
  { icon: Search, label: "定位一个问题", prompt: "请帮我定位一个前端问题，先读相关代码再给出修复方案。" },
  { icon: WandSparkles, label: "实现一个改动", prompt: "请根据现有代码风格，实现一个小改动并完成验证。" },
];

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
  const currentModel = useAgentStore((state) => state.currentModel);
  const currentProviderId = useAgentStore((state) => state.currentProviderId);
  const providers = useAgentStore((state) => state.providers);
  const workspace = useAgentStore((state) => state.workspace);

  const [panelOpen, setPanelOpen] = useState(false);
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
    // 首次出现本会话的子 agent 运行时自动展开面板，让编排过程"开箱可见"。
    if (lastRunId.startsWith(`${sessionId}:`)) setPanelOpen(true);
  }, [lastRunId, sessionId]);

  const activeSession = sessions.find((item) => item.id === sessionId) ?? sessions.find((item) => item.id === currentSessionId);
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
        <div className="justify-self-center text-sm font-medium text-[var(--as-text)]">新线程</div>
        <div className="flex justify-self-end gap-2">
          <button
            type="button"
            onClick={() => setPanelOpen((value) => !value)}
            className={`relative flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] transition ${
              panelOpen
                ? "border-[var(--as-accent)] bg-[var(--as-surface)] text-[var(--as-accent-soft)]"
                : "border-[var(--as-border-strong)] bg-[var(--as-surface)] text-[var(--as-text-secondary)] hover:border-[var(--as-accent)] hover:text-[var(--as-accent-soft)]"
            }`}
            title="子 Agent 面板"
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
          ) : (
            <EmptySessionState enabled={suggestionsEnabled} onPick={(prompt) => void sendInSession(prompt)} />
          )}
          <div className="absolute bottom-10 left-0 right-0 px-6">
            <InputBar status={status} onSend={(text, options) => void sendInSession(text, options)} onAbort={abortRun} compact />
          </div>
        </div>
        {panelOpen ? <SubAgentPanel sessionId={sessionId} onClose={() => setPanelOpen(false)} /> : null}
      </div>
    </div>
  );
}

function EmptySessionState({ enabled, onPick }: { enabled: boolean; onPick: (prompt: string) => void }) {
  return (
    <main className="flex min-h-0 flex-1 items-center justify-center px-6 py-10">
      <div className="w-full max-w-[620px] text-center">
        <div className="mt-5 grid gap-2 sm:grid-cols-3">
          {EMPTY_SUGGESTIONS.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.label}
                type="button"
                disabled={!enabled}
                onClick={() => onPick(item.prompt)}
                className="group rounded-[11px] border border-[var(--as-border)] bg-[var(--as-surface-low)] p-3 text-left text-[12px] text-[var(--as-text-secondary)] transition hover:-translate-y-0.5 hover:border-[var(--as-border-strong)] hover:bg-[var(--as-hover)] hover:text-[var(--as-text)] disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0"
              >
                <Icon size={15} className="mb-2 text-[var(--as-accent)]" />
                <span>{item.label}</span>
              </button>
            );
          })}
        </div>
      </div>
    </main>
  );
}

function ConnectionBanner({ state, onReconnect }: { state: "reconnecting" | "disconnected"; onReconnect: () => void }) {
  const reconnecting = state === "reconnecting";
  return (
    <div className="flex shrink-0 items-center justify-center gap-2.5 border-b border-[var(--as-border)] bg-[var(--as-surface)] px-5 py-1.5 text-[12px]">
      <span className={`h-1.5 w-1.5 rounded-full bg-[var(--as-danger)] ${reconnecting ? "animate-pulse" : ""}`} />
      <span className="text-[var(--as-text-secondary)]">{reconnecting ? "连接已断开，正在重连…" : "连接已断开"}</span>
      {reconnecting ? null : (
        <button
          type="button"
          onClick={onReconnect}
          className="rounded-md border border-[var(--as-border-strong)] bg-[var(--as-bg)] px-2 py-0.5 text-[11px] text-[var(--as-text)] transition hover:border-[var(--as-accent)] hover:text-[var(--as-accent-soft)]"
        >
          点击重连
        </button>
      )}
    </div>
  );
}
