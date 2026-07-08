import { useEffect, useState } from "react";

import DiffViewer from "@/components/diff/DiffViewer";
import type { ToolCall, ToolResult } from "@/types";

interface ToolCallLineProps {
  call: ToolCall;
  result?: ToolResult;
  pending?: boolean;
  awaitingApproval?: boolean;
  onApprove?: () => void;
  onReject?: () => void;
}

const asRecord = (value: unknown): Record<string, unknown> =>
  typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};

const truncate = (value: string, max = 50): string => (value.length > max ? `${value.slice(0, max)}...` : value);

const summarizeOutput = (value: string, max = 120): string => {
  const firstLine = value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean);
  return firstLine ? truncate(firstLine, max) : "命令失败，但没有返回更多输出。";
};

const summarizeArgs = (call: ToolCall): string => {
  const args = asRecord(call.arguments);
  const name = call.name.toLowerCase();
  const command = typeof args.command === "string" ? args.command : "";
  const path = typeof args.path === "string" ? args.path : "";

  if (name.includes("bash")) return truncate(command || JSON.stringify(call.arguments ?? {}));
  if (name.includes("read")) return truncate(path || JSON.stringify(call.arguments ?? {}));
  if (name.includes("write")) return truncate(path || JSON.stringify(call.arguments ?? {}));

  try {
    return truncate(JSON.stringify(call.arguments ?? {}));
  } catch {
    return "";
  }
};

export default function ToolCallLine({ call, result, pending = false, awaitingApproval = false, onApprove, onReject }: ToolCallLineProps) {
  const [expanded, setExpanded] = useState(false);
  const label = `${call.name}(${summarizeArgs(call)})`;

  useEffect(() => {
    if (result?.isError) setExpanded(true);
  }, [result?.isError]);

  if (awaitingApproval) {
    return (
      <div className="flex flex-col gap-2 py-1 font-sans text-sm">
        <div className="flex items-center gap-2 text-[var(--as-text-secondary)]">
          <span className="text-xs text-[var(--as-danger)]">!</span>
          <span className="min-w-0 break-words">需要审批 {label}</span>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={onApprove} className="as-primary-btn h-7 px-3 text-xs">
            批准
          </button>
          <button
            type="button"
            onClick={onReject}
            className="inline-flex h-7 items-center justify-center rounded-lg border border-[var(--as-border-strong)] px-3 text-xs text-[var(--as-danger)] transition hover:border-[var(--as-danger)] hover:bg-[var(--as-hover)]"
          >
            拒绝
          </button>
        </div>
      </div>
    );
  }

  if (pending) {
    return (
      <div className="tool-shimmer flex items-center gap-2 py-1 font-sans text-sm text-[#999999]">
        <span className="text-xs">...</span>
        <span>正在运行 {label}</span>
      </div>
    );
  }

  if (!result) return null;

  return (
    <div className="group flex items-start gap-2 py-1 font-sans text-sm">
      <span className={`mt-0.5 text-xs ${result.isError ? "text-red-500" : "text-emerald-500"}`}>
        {result.isError ? "x" : "ok"}
      </span>
      <div className="min-w-0">
        <button
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          className="text-left text-[#666666] transition hover:text-[#999999]"
        >
          已运行 {label}
          <span className="ml-2 text-xs opacity-0 transition group-hover:opacity-100">
            {expanded ? "收起" : "查看输出"}
          </span>
        </button>
        {result.isError ? (
          <div className="mt-1 whitespace-pre-wrap text-xs text-red-400">
            {summarizeOutput(result.output)}
          </div>
        ) : null}
        {expanded && result.output ? (
          <div className="mt-1 max-h-48 overflow-x-auto overflow-y-auto whitespace-pre-wrap break-words rounded bg-[var(--as-code-bg)] p-2 text-xs leading-5 text-[var(--as-text-muted)]">
            {result.output}
          </div>
        ) : null}
        {expanded && result.diffs?.length ? (
          <div className="mt-2 max-h-96 space-y-2 overflow-y-auto">
            {result.diffs.map((diff, index) => (
              <DiffViewer
                key={`${diff.path}-${index}`}
                filename={diff.path}
                unifiedDiff={diff.unifiedDiff}
              />
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
