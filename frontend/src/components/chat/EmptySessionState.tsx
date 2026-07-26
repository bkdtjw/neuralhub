import { Bot, Code2, Plug, Search, WandSparkles, type LucideIcon } from "lucide-react";
import { useNavigate } from "react-router-dom";

import EmptyState from "@/components/common/EmptyState";

const EMPTY_SUGGESTIONS: { icon: LucideIcon; label: string; prompt: string }[] = [
  { icon: Code2, label: "梳理当前项目结构", prompt: "请先阅读当前项目结构，告诉我主要模块和入口文件。" },
  { icon: Search, label: "定位一个问题", prompt: "请帮我定位一个前端问题，先读相关代码再给出修复方案。" },
  { icon: WandSparkles, label: "实现一个改动", prompt: "请根据现有代码风格，实现一个小改动并完成验证。" },
];

export default function EmptySessionState({
  configured,
  enabled,
  onPick,
}: {
  configured: boolean;
  enabled: boolean;
  onPick: (prompt: string) => void;
}) {
  const navigate = useNavigate();
  if (!configured) {
    return (
      <main className="flex min-h-0 flex-1 items-center justify-center px-6 py-10">
        <div className="w-full max-w-[400px]">
          <EmptyState
            icon={Plug}
            title="尚未配置模型 Provider"
            description="先添加一个 LLM Provider 并选择模型，即可开始对话"
            action={{ label: "前往设置", onClick: () => navigate("/settings") }}
          />
        </div>
      </main>
    );
  }
  return (
    <main className="flex min-h-0 flex-1 items-center justify-center px-6 py-10">
      <div className="w-full max-w-[620px] text-center">
        <EmptyState icon={Bot} title="NeuralHub" description="选一个开场，或直接输入你的任务">
          <div className="mt-5 grid w-full gap-2 sm:grid-cols-3">
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
        </EmptyState>
      </div>
    </main>
  );
}
