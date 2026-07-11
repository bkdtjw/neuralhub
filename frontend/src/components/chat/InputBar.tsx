import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { FolderOpen, SendHorizontal, Square } from "lucide-react";

import { providerModels, supportsThinking } from "@/lib/model-capabilities";
import InputKnowledgeControls from "@/components/knowledge/InputKnowledgeControls";
import { useAgentStore } from "@/stores/agentStore";
import type { AgentStatus, ChatRunOptions, ThinkingLevel } from "@/types";

interface InputBarProps {
  status: AgentStatus;
  onSend: (text: string, options?: ChatRunOptions) => void;
  onAbort: () => void;
  compact?: boolean;
}

const runningStatuses: AgentStatus[] = ["thinking", "compacting", "tool_calling", "waiting_approval"];

const statusText = (status: AgentStatus): string => {
  if (status === "thinking") return "生成中";
  if (status === "compacting") return "压缩上下文";
  if (status === "tool_calling") return "执行工具";
  if (status === "waiting_approval") return "等待工具审批";
  if (status === "error") return "请求失败";
  return "就绪";
};

const modeLabels = {
  readonly: "只读",
  auto: "默认权限",
  full: "完全访问",
} as const;

const thinkingLevels: { value: ThinkingLevel; label: string }[] = [
  { value: "low", label: "低" },
  { value: "medium", label: "中" },
  { value: "high", label: "高" },
];

export default function InputBar({ status, onSend, onAbort, compact = false }: InputBarProps) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const currentModel = useAgentStore((state) => state.currentModel);
  const currentProviderId = useAgentStore((state) => state.currentProviderId);
  const providers = useAgentStore((state) => state.providers);
  const setModel = useAgentStore((state) => state.setModel);
  const setProvider = useAgentStore((state) => state.setProvider);
  const workspace = useAgentStore((state) => state.workspace);
  const permissionMode = useAgentStore((state) => state.permissionMode);
  const setPermissionMode = useAgentStore((state) => state.setPermissionMode);
  const thinkingLevel = useAgentStore((state) => state.thinkingLevel);
  const setThinkingLevel = useAgentStore((state) => state.setThinkingLevel);

  const running = runningStatuses.includes(status);
  const currentProvider = providers.find((item) => item.id === currentProviderId) ?? null;
  const modelOptions = providerModels(currentProvider);
  const thinkingAvailable = supportsThinking(currentProvider, currentModel);
  const canSend = Boolean(text.trim() && currentProvider && currentModel && !running);
  const thinkingIndex = thinkingLevels.findIndex((item) => item.value === thinkingLevel);
  const workspaceLabel = workspace ? workspace.split(/[/\\]/).filter(Boolean).pop() ?? workspace : "工作区";

  const resize = () => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    const maxHeight = 24 * 6;
    textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`;
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? "auto" : "hidden";
  };

  useEffect(() => {
    resize();
  }, [text]);

  const handleSend = () => {
    const value = text.trim();
    if (!canSend) return;
    onSend(value, { thinkingLevel: thinkingAvailable ? thinkingLevel : undefined });
    setText("");
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    handleSend();
  };

  return (
    <div className={`shrink-0 ${compact ? "" : "pb-2"} pt-2`}>
      <div className="mx-auto w-full max-w-[1120px] rounded-xl border border-[var(--as-border-strong)] bg-[var(--as-surface)] px-4 py-4 shadow-[var(--as-shadow)] focus-within:border-[var(--as-accent)]">
        <textarea
          ref={textareaRef}
          value={text}
          disabled={running || !currentProvider || !currentModel}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          placeholder={currentProvider && currentModel ? "向 NeuralHub 发送消息" : "先在设置中配置并启用 Provider"}
          className="max-h-36 min-h-[64px] w-full resize-none bg-transparent text-[13px] leading-6 text-[var(--as-text)] outline-none placeholder:text-[var(--as-text-subtle)] disabled:cursor-not-allowed"
        />
        <div className="mt-3 flex items-center gap-3">
          <div className="flex min-w-0 flex-1 items-center gap-2 overflow-x-auto pb-0.5 text-xs text-[var(--as-text-muted)] [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <button
              type="button"
              title={workspace || "选择工作区"}
              onClick={() => void useAgentStore.getState().openFolder()}
              className="flex h-9 w-[104px] shrink-0 items-center gap-1.5 rounded-[7px] border border-[var(--as-border-strong)] bg-[var(--as-bg)] px-2.5 text-[11px] text-[var(--as-text-secondary)] hover:border-[#2b2b31] hover:bg-[var(--as-hover)] hover:text-[var(--as-text)]"
            >
              <FolderOpen size={13} className="shrink-0 text-[var(--as-text-muted)]" />
              <span className="min-w-0 truncate">{workspaceLabel}</span>
            </button>
            <InputKnowledgeControls running={running} />
            <select
              value={currentProviderId ?? ""}
              disabled={!providers.length || running}
              onChange={(event) => event.target.value && setProvider(event.target.value)}
              className="as-select w-[116px] shrink-0 font-mono"
            >
              {!providers.length ? <option value="">未配置 Provider</option> : null}
              {providers.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name}
                </option>
              ))}
            </select>
            <select
              value={currentModel}
              disabled={!modelOptions.length || running}
              onChange={(event) => setModel(event.target.value)}
              className="as-select w-[150px] shrink-0 font-mono"
            >
              {!modelOptions.length ? <option value="">无可用模型</option> : null}
              {modelOptions.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
            {thinkingAvailable ? (
              <>
              <span className="shrink-0 text-[11px] text-[var(--as-text-muted)]">推理强度</span>
              <div className="relative grid h-9 w-[118px] shrink-0 grid-cols-3 rounded-[7px] border border-[var(--as-border-strong)] bg-[var(--as-bg)] p-0.5">
                <span
                  className="absolute left-0.5 top-0.5 h-8 rounded-md transition-transform duration-150"
                  style={{
                    width: "calc((100% - 4px) / 3)",
                    transform: `translateX(${Math.max(thinkingIndex, 0) * 100}%)`,
                    background: thinkingLevel === "high" ? "var(--as-thinking)" : "var(--as-accent)",
                  }}
                />
                {thinkingLevels.map((level) => (
                  <button
                    key={level.value}
                    type="button"
                    disabled={running}
                    onClick={() => setThinkingLevel(level.value)}
                    className={`relative z-10 rounded-[5px] text-[11px] hover:text-[var(--as-text)] disabled:cursor-not-allowed ${
                      thinkingLevel === level.value ? "text-white" : "text-[var(--as-text-secondary)]"
                    }`}
                  >
                    {level.label}
                  </button>
                ))}
              </div>
              </>
            ) : null}
            <select
              value={permissionMode}
              disabled={running}
              onChange={(event) => setPermissionMode(event.target.value as keyof typeof modeLabels)}
              className="as-select w-[120px] shrink-0"
            >
              {Object.entries(modeLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div className="ml-auto flex shrink-0 items-center gap-2">
            {!compact ? <span className="hidden text-[11px] text-[var(--as-text-subtle)] sm:inline">{statusText(status)}</span> : null}
            <button
              type="button"
              disabled={!running && !canSend}
              onClick={running ? onAbort : handleSend}
              className="as-primary-btn h-10 gap-1.5 px-4 text-sm disabled:cursor-not-allowed disabled:opacity-45"
            >
              {running ? <Square size={14} fill="currentColor" /> : <SendHorizontal size={15} />}
              <span>{running ? "停止" : "发送"}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
