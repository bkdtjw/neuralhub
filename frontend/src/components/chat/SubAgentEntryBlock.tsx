import { Hammer, MessageSquare, Undo2 } from "lucide-react";

const KIND_META: Record<string, { label: string; Icon: typeof Hammer }> = {
  tool_call: { label: "工具调用", Icon: Hammer },
  tool_result: { label: "工具结果", Icon: Undo2 },
  message: { label: "消息", Icon: MessageSquare },
};

/** 子 agent 转录抽屉里的单条活动卡片（工具调用/结果/消息通用）。 */
export default function SubAgentEntryBlock({
  kind,
  content,
  isError,
  time,
}: {
  kind: string;
  content: string;
  isError: boolean;
  time: string;
}) {
  const meta = KIND_META[kind] ?? KIND_META.message;
  return (
    <div className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-low)]">
      <div className="flex items-center gap-1.5 border-b border-[var(--as-border)] px-2.5 py-1 text-[10px] text-[var(--as-text-subtle)]">
        <meta.Icon size={11} className="shrink-0" />
        <span>{meta.label}</span>
        {isError ? <span className="text-[var(--as-danger)]">出错</span> : null}
        <span className="ml-auto font-mono">{time}</span>
      </div>
      <pre className="max-h-[360px] overflow-y-auto overscroll-contain whitespace-pre-wrap break-all px-2.5 py-2 font-mono text-[11px] leading-4 text-[var(--as-text-secondary)]">
        {content}
      </pre>
    </div>
  );
}
