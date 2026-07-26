import { useEffect, useRef } from "react";
import { AlertTriangle, RefreshCw, X } from "lucide-react";

import SubAgentEntryBlock from "@/components/chat/SubAgentEntryBlock";
import { PINNED_THRESHOLD_PX } from "@/components/chat/auto-scroll";
import { useSubAgentTranscript } from "@/components/chat/use-sub-agent-transcript";
import type { SubAgentEntry } from "@/stores/subAgentStore";

const STATUS_META: Record<string, { label: string; dot: string }> = {
  pending: { label: "等待", dot: "bg-[var(--as-text-subtle)]" },
  running: { label: "运行中", dot: "animate-pulse bg-[var(--as-thinking)]" },
  done: { label: "完成", dot: "bg-[var(--as-success)]" },
  failed: { label: "失败", dot: "bg-[var(--as-danger)]" },
  skipped: { label: "跳过", dot: "bg-[var(--as-text-subtle)]" },
};

const formatTime = (tsMs: number): string =>
  Number.isFinite(tsMs) && tsMs > 0 ? new Date(tsMs).toLocaleTimeString() : "";

export default function SubAgentDetail({
  rawRunId,
  agent,
  onClose,
}: {
  rawRunId: string;
  agent: SubAgentEntry;
  onClose: () => void;
}) {
  const { transcript, fetchError, updatedAt, refresh } = useSubAgentTranscript(rawRunId, agent.role, agent.status);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const pinnedRef = useRef(true);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // 贴底自动跟随：沿用 auto-scroll.ts 的贴底阈值，仅在用户已贴近底部时吸底，
  // 向上翻阅历史时不被新条目强行拽回。
  const entryCount = transcript?.entries.length ?? 0;
  useEffect(() => {
    const el = scrollRef.current;
    if (el && pinnedRef.current) el.scrollTop = el.scrollHeight;
  }, [entryCount]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (el) pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < PINNED_THRESHOLD_PX;
  };

  const status = STATUS_META[transcript?.status ?? agent.status] ?? STATUS_META.pending;
  const stage = transcript?.stage ?? agent.stage;
  const errorText = transcript?.error || agent.error || "";

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={onClose} role="presentation">
      <section
        className="flex h-full w-[560px] max-w-[92vw] flex-col border-l border-[var(--as-border)] bg-[var(--as-surface)] shadow-[var(--as-shadow)]"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex h-11 shrink-0 items-center gap-2 border-b border-[var(--as-border)] px-3">
          <span className={`h-2 w-2 shrink-0 rounded-full ${status.dot}`} />
          <span className="truncate text-[13px] font-medium text-[var(--as-text)]">{agent.role}</span>
          <span className="shrink-0 text-[11px] text-[var(--as-text-subtle)]">{status.label}</span>
          {stage !== undefined && stage !== null ? (
            <span className="shrink-0 rounded border border-[var(--as-border-strong)] bg-[var(--as-surface-low)] px-1.5 py-0.5 text-[10px] text-[var(--as-text-secondary)]">
              阶段 {stage}
            </span>
          ) : null}
          <div className="ml-auto flex shrink-0 items-center gap-1">
            {updatedAt > 0 ? (
              <span className="font-mono text-[10px] text-[var(--as-text-subtle)]">更新于 {formatTime(updatedAt)}</span>
            ) : null}
            <button
              type="button"
              onClick={refresh}
              className="rounded p-1 text-[var(--as-text-subtle)] transition hover:bg-[var(--as-hover)] hover:text-[var(--as-text)]"
              aria-label="手动刷新转录"
            >
              <RefreshCw size={13} />
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded p-1 text-[var(--as-text-subtle)] transition hover:bg-[var(--as-hover)] hover:text-[var(--as-text)]"
              aria-label="关闭子 Agent 详情"
            >
              <X size={14} />
            </button>
          </div>
        </header>
        <div ref={scrollRef} onScroll={handleScroll} className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
          {transcript ? (
            <>
              {transcript.dropped > 0 ? (
                <p className="text-[11px] text-[var(--as-text-subtle)]">
                  记录过多，最早的 {transcript.dropped} 条已被滚动淘汰。
                </p>
              ) : null}
              {transcript.entries.length === 0 ? (
                <p className="pt-2 text-[12px] text-[var(--as-text-subtle)]">该子 agent 暂无活动记录。</p>
              ) : (
                transcript.entries.map((entry, index) => (
                  <SubAgentEntryBlock
                    key={index}
                    kind={entry.kind}
                    content={entry.content}
                    isError={entry.is_error}
                    time={formatTime(entry.ts * 1000)}
                  />
                ))
              )}
            </>
          ) : fetchError ? (
            <>
              <div className="flex items-start gap-2 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-low)] px-2.5 py-2 text-[11px] leading-4 text-[var(--as-text-secondary)]">
                <AlertTriangle size={12} className="mt-0.5 shrink-0 text-[var(--as-danger)]" />
                <span>完整转录不可用（{fetchError}），以下为实时预览（每条最多 160 字符）。</span>
                <button
                  type="button"
                  onClick={refresh}
                  className="ml-auto shrink-0 rounded p-1 text-[var(--as-text-subtle)] transition hover:bg-[var(--as-hover)] hover:text-[var(--as-text)]"
                  aria-label="重新拉取转录"
                >
                  <RefreshCw size={12} />
                </button>
              </div>
              {agent.activities.map((activity, index) => (
                <SubAgentEntryBlock
                  key={index}
                  kind={activity.kind}
                  content={activity.preview}
                  isError={false}
                  time={formatTime(activity.ts)}
                />
              ))}
            </>
          ) : (
            <p className="pt-2 text-[12px] text-[var(--as-text-subtle)]">正在加载完整转录…</p>
          )}
          {errorText ? (
            <div className="rounded-lg border border-[var(--as-danger)] px-2.5 py-2 text-[11px] leading-4 text-[var(--as-danger)]">
              {errorText}
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
