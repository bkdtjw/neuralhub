import { Loader2, Pencil, Radar, Trash2 } from "lucide-react";

import { STATUS_CLASS, STATUS_LABEL, formatTs, sourceLabel } from "@/components/hooks/status";
import type { EventHook, HookSummary, SourceHealth, TimelineEntry } from "@/types/hooks";

interface HookDetailProps {
  summary: HookSummary | null;
  usingMock: boolean;
  scanningId: string;
  onRun: (id: string) => void;
  onEdit: (id: string) => void;
  onDelete: (id: string) => void;
}

export default function HookDetail({ summary, usingMock, scanningId, onRun, onEdit, onDelete }: HookDetailProps) {
  if (!summary) {
    return (
      <main className="as-glass grid min-h-[460px] place-items-center rounded-2xl text-sm text-[var(--as-text-muted)]">
        选择左侧钩子查看动态
      </main>
    );
  }
  const { hook, state } = summary;
  const status = state?.status ?? "developing";
  const scanning = scanningId === hook.id;
  return (
    <main className="as-glass min-w-0 rounded-2xl p-5">
      <header className="flex flex-col gap-3 border-b border-white/10 pb-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-lg font-semibold text-[var(--as-text-bright)]">{hook.name}</h1>
            <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs ${STATUS_CLASS[status]}`}>{STATUS_LABEL[status]}</span>
          </div>
          <p className="mt-1.5 text-sm leading-relaxed text-[var(--as-text-secondary)]">{state?.summary || "尚未扫描"}</p>
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={() => onRun(hook.id)}
            disabled={usingMock || scanning}
            title={usingMock ? "演示数据模式不可扫描" : "立即扫描（X+Exa+LLM，约几秒）"}
            className="as-glass-accent inline-flex h-9 items-center gap-1.5 rounded-[10px] px-3 text-sm font-medium"
          >
            {scanning ? <Loader2 size={14} className="animate-spin" /> : <Radar size={14} />}
            {scanning ? "扫描中" : "扫描"}
          </button>
          <button type="button" onClick={() => onEdit(hook.id)} className="as-glass-btn inline-flex h-9 items-center gap-1.5 rounded-[10px] px-3 text-sm">
            <Pencil size={14} /> 编辑
          </button>
          <button type="button" onClick={() => onDelete(hook.id)} className="as-glass-btn inline-flex h-9 items-center justify-center rounded-[10px] px-2.5 text-rose-300">
            <Trash2 size={14} />
          </button>
        </div>
      </header>
      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_244px]">
        <section className="min-w-0">
          <MonitorMeta hook={hook} />
          <Timeline entries={state?.timeline ?? []} />
        </section>
        <aside className="space-y-4">
          <Confidence value={state?.confidence ?? 0} materiality={hook.materiality} />
          <SourceHealthCard health={state?.sourceHealth ?? []} lastScanned={state?.lastScanned ?? ""} cadence={hook.cadenceMinutes} />
        </aside>
      </div>
    </main>
  );
}

function MonitorMeta({ hook }: { hook: EventHook }) {
  const { accounts, keywords } = hook.twitter;
  const chip = (value: string, prefix: string) => (
    <span key={prefix + value} className="rounded-md border border-white/10 bg-white/[0.06] px-2 py-0.5 text-xs text-[var(--as-text-secondary)]">
      {prefix}
      {value}
    </span>
  );
  return (
    <div className="mb-4 flex flex-wrap gap-1.5">
      {accounts.map((value) => chip(value, "@"))}
      {keywords.map((value) => chip(value, "#"))}
      {!accounts.length && !keywords.length ? <span className="text-xs text-[var(--as-text-muted)]">未设监控目标</span> : null}
    </div>
  );
}

function Timeline({ entries }: { entries: TimelineEntry[] }) {
  if (!entries.length) {
    return <div className="as-glass-inset rounded-xl py-12 text-center text-sm text-[var(--as-text-muted)]">暂无动态，等待首次扫描</div>;
  }
  return (
    <ol className="space-y-2">
      {entries.map((entry, index) => (
        <li key={`${entry.ts}-${index}`} className="flex gap-3">
          <div className="mt-1.5 flex flex-col items-center">
            <span className={`h-2.5 w-2.5 rounded-full ${entry.isNew ? "bg-sky-400 shadow-[0_0_8px_rgba(56,189,248,0.7)]" : "bg-white/20"}`} />
            {index < entries.length - 1 ? <span className="mt-1 w-px flex-1 bg-gradient-to-b from-white/15 to-transparent" /> : null}
          </div>
          <div className="as-glass-inset min-w-0 flex-1 rounded-xl px-3 py-2.5">
            <div className="text-sm leading-relaxed text-[var(--as-text)]">{entry.text}</div>
            <div className="mt-1.5 flex items-center gap-2 text-[10px] text-[var(--as-text-muted)]">
              <span className="rounded border border-white/10 bg-white/[0.06] px-1.5 py-0.5">{sourceLabel(entry.source)}</span>
              <span className="font-mono tabular-nums">{formatTs(entry.ts)}</span>
              {entry.isNew ? <span className="text-sky-300">新</span> : null}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}

function Confidence({ value, materiality }: { value: number; materiality: number }) {
  const clamped = Math.min(100, Math.max(0, value));
  return (
    <div className="as-glass-inset rounded-xl p-3.5">
      <div className="flex items-center justify-between text-xs text-[var(--as-text-muted)]">
        <span>置信度</span>
        <span className="font-mono text-base tabular-nums text-[var(--as-text-bright)]">{clamped}</span>
      </div>
      <div className="relative mt-2.5 h-2 rounded-full bg-black/30">
        <div
          className="h-full rounded-full bg-[linear-gradient(90deg,#38bdf8,#6366f1)] shadow-[0_0_10px_rgba(99,102,241,0.5)]"
          style={{ width: `${clamped}%` }}
        />
        <div className="absolute -top-1 h-4 w-0.5 rounded bg-white/70 shadow-[0_0_6px_rgba(255,255,255,0.5)]" style={{ left: `${materiality}%` }} />
      </div>
      <div className="mt-2 text-[10px] leading-relaxed text-[var(--as-text-muted)]">竖线=推送门槛 {materiality}，越过才推飞书</div>
    </div>
  );
}

function SourceHealthCard({ health, lastScanned, cadence }: { health: SourceHealth[]; lastScanned: string; cadence: number }) {
  return (
    <div className="as-glass-inset rounded-xl p-3.5">
      <div className="mb-2.5 text-xs font-medium text-[var(--as-text-secondary)]">数据源</div>
      <div className="space-y-2">
        {health.map((item) => (
          <div key={item.source} className="flex items-center justify-between text-xs">
            <span className="flex items-center gap-1.5 text-[var(--as-text)]">
              <span className={`h-1.5 w-1.5 rounded-full ${item.online ? "bg-emerald-400 shadow-[0_0_7px_rgba(52,211,153,0.7)]" : "bg-rose-400/70"}`} />
              {sourceLabel(item.source)}
            </span>
            <span className="text-[var(--as-text-muted)]">
              {item.online ? "正常" : "静默"} · <span className="font-mono tabular-nums">{formatTs(item.lastOk)}</span>
            </span>
          </div>
        ))}
        {!health.length ? <div className="text-xs text-[var(--as-text-muted)]">无</div> : null}
      </div>
      <div className="mt-2.5 border-t border-white/10 pt-2.5 text-[10px] leading-relaxed text-[var(--as-text-muted)]">
        每 {cadence} 分钟扫描 · 上次 <span className="font-mono tabular-nums">{formatTs(lastScanned)}</span>
      </div>
    </div>
  );
}
