import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Code2, Search, Sparkles, WandSparkles } from "lucide-react";

import InputBar from "@/components/chat/InputBar";
import HomeModeTabs from "@/components/knowledge/HomeModeTabs";
import KnowledgeHomePanel from "@/components/knowledge/KnowledgeHomePanel";
import KnowledgeStatusPill from "@/components/knowledge/KnowledgeStatusPill";
import { useAgentStore } from "@/stores/agentStore";
import { useKnowledgeStore } from "@/stores/knowledgeStore";
import { useSessionStore } from "@/stores/sessionStore";
import type { ChatRunOptions } from "@/types";

const suggestions = [
  { icon: Code2, text: "梳理这个项目的启动流程", prompt: "帮我梳理当前项目的启动流程，并指出关键入口文件。" },
  { icon: Search, text: "检查最近的错误日志", prompt: "帮我检查最近的错误日志，按影响范围总结问题。" },
  { icon: WandSparkles, text: "实现一个小功能", prompt: "我想实现一个小功能，先帮我阅读项目结构并给出实现方案。" },
];

export default function Dashboard() {
  const navigate = useNavigate();
  const [startError, setStartError] = useState("");
  const createSession = useSessionStore((state) => state.createSession);
  const startDraftSession = useSessionStore((state) => state.startDraftSession);
  const model = useAgentStore((state) => state.currentModel);
  const providerId = useAgentStore((state) => state.currentProviderId);
  const providers = useAgentStore((state) => state.providers);
  const workspace = useAgentStore((state) => state.workspace);
  const knowledgeMode = useKnowledgeStore((state) => state.mode);
  const loadKnowledge = useKnowledgeStore((state) => state.loadAll);
  const workspaceName = workspace?.split(/[/\\]/).pop();
  const currentProvider = providers.find((provider) => provider.id === providerId);
  const modelLabel = [currentProvider?.name, model].filter(Boolean).join(" · ");
  const activeSuggestions = knowledgeMode === "knowledge" ? [] : suggestions;

  useEffect(() => {
    startDraftSession();
    void loadKnowledge();
  }, [loadKnowledge, startDraftSession]);

  const startChat = async (prompt?: string, options?: ChatRunOptions) => {
    const content = prompt?.trim() ?? "";
    if (!content) return;
    setStartError("");
    if (!providerId || !model) {
      navigate("/settings");
      return;
    }
    try {
      const id = await createSession(model, providerId, content);
      navigate(`/session/${id}`, { state: { initialPrompt: content, ...options } });
    } catch (error) {
      console.error("create session failed", error);
      setStartError(error instanceof Error && error.message ? error.message : "创建会话失败，请稍后重试");
    }
  };

  return (
    <div className="relative flex h-full min-h-0 flex-col bg-[var(--as-bg)]">
      <header className="grid h-12 shrink-0 grid-cols-[160px_1fr_220px] items-center border-b border-[var(--as-border)] px-5">
        <div className="text-xs text-[var(--as-text-subtle)]">{workspaceName ? `项目：${workspaceName}` : ""}</div>
        <div className="justify-self-center text-sm font-medium text-[var(--as-text)]">新线程</div>
        <div className="flex justify-self-end gap-2">
          <KnowledgeStatusPill />
          {modelLabel ? (
            <span className="rounded-md border border-[var(--as-border-strong)] bg-[var(--as-surface)] px-2.5 py-1 font-mono text-[11px] text-[var(--as-text-secondary)]">
              {modelLabel}
            </span>
          ) : null}
        </div>
      </header>

      <div className="flex flex-1 flex-col items-center justify-center px-8 pb-44">
        <div className="flex w-full max-w-[760px] flex-col items-center">
          <div className="relative flex h-[60px] w-[60px] items-center justify-center rounded-2xl border border-[var(--as-border-strong)] bg-[linear-gradient(145deg,#16161c,#0e0e12)] shadow-[0_18px_42px_rgb(0_0_0_/_28%)]">
            <span className="absolute inset-x-2 top-1 h-px bg-white/10" />
            <Sparkles size={24} strokeWidth={1.8} className="text-[var(--as-accent-soft)]" />
          </div>
          <h2 className="mt-5 text-lg font-medium text-[var(--as-text-bright)]">开始构建</h2>
          <p className="mt-2 text-center text-[13px] text-[var(--as-text-muted)]">选择工作模式，然后描述你想做什么</p>
          <div className="mt-7 w-full max-w-[460px]">
            <HomeModeTabs />
          </div>
          {!providers.length ? (
            <button type="button" onClick={() => navigate("/settings")} className="as-primary-btn mt-4 px-4 py-2 text-sm">
              配置 Provider
            </button>
          ) : null}
          {knowledgeMode === "knowledge" ? <KnowledgeHomePanel onAsk={(prompt) => void startChat(prompt)} /> : null}
          <div className={`grid w-full grid-cols-1 gap-2 sm:grid-cols-3 ${activeSuggestions.length ? "mt-7" : ""}`}>
            {activeSuggestions.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.text}
                  type="button"
                  disabled={!providers.length}
                  onClick={() => void startChat(item.prompt)}
                  className="group rounded-[11px] border border-[#1f1f26] bg-[var(--as-surface-low)] p-3 text-left transition hover:-translate-y-0.5 hover:border-[#2b2b31] hover:bg-[var(--as-surface)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Icon size={16} className="mb-2 text-[var(--as-accent)] transition group-hover:text-[var(--as-accent-soft)]" />
                  <div className="text-xs leading-5 text-[var(--as-text-secondary)] group-hover:text-[var(--as-text)]">{item.text}</div>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div className="absolute bottom-10 left-0 right-0 px-6">
        {startError ? (
          <div className="mx-auto mb-2 w-full max-w-[1120px] text-center text-[12px] text-[#ff7b72]">{startError}</div>
        ) : null}
        <InputBar status="idle" onSend={(text, options) => void startChat(text, options)} onAbort={() => {}} compact />
      </div>
    </div>
  );
}
