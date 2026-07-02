import { useEffect, useState } from "react";
import { Radar } from "lucide-react";

import HookDetail from "@/components/hooks/HookDetail";
import HookForm from "@/components/hooks/HookForm";
import HookList from "@/components/hooks/HookList";
import { useHooksStore } from "@/stores/hooksStore";
import type { HookDraft, HookSummary } from "@/types/hooks";

type FormTarget = { mode: "new" } | { mode: "edit"; summary: HookSummary } | null;

export default function Hooks() {
  const summaries = useHooksStore((state) => state.summaries);
  const currentId = useHooksStore((state) => state.currentId);
  const loading = useHooksStore((state) => state.loading);
  const error = useHooksStore((state) => state.error);
  const usingMock = useHooksStore((state) => state.usingMock);
  const loadAll = useHooksStore((state) => state.loadAll);
  const startPolling = useHooksStore((state) => state.startPolling);
  const stopPolling = useHooksStore((state) => state.stopPolling);
  const selectHook = useHooksStore((state) => state.selectHook);
  const createHook = useHooksStore((state) => state.createHook);
  const updateHook = useHooksStore((state) => state.updateHook);
  const deleteHook = useHooksStore((state) => state.deleteHook);
  const runHook = useHooksStore((state) => state.runHook);
  const scanningId = useHooksStore((state) => state.scanningId);
  const scanNote = useHooksStore((state) => state.scanNote);

  const [form, setForm] = useState<FormTarget>(null);

  useEffect(() => {
    void loadAll();
    startPolling();
    return () => stopPolling();
  }, [loadAll, startPolling, stopPolling]);

  const current = summaries.find((item) => item.hook.id === currentId) ?? null;

  const onEdit = (id: string) => {
    const target = summaries.find((item) => item.hook.id === id);
    if (target) setForm({ mode: "edit", summary: target });
  };
  const onDelete = (id: string) => {
    const target = summaries.find((item) => item.hook.id === id);
    if (target && window.confirm(`删除钩子「${target.hook.name}」？`)) void deleteHook(id);
  };
  const onSubmit = async (draft: HookDraft) => {
    if (form?.mode === "edit") await updateHook(form.summary.hook.id, draft);
    else await createHook(draft);
  };

  return (
    <div className="as-hooks-bg h-full overflow-y-auto px-6 py-7">
      <div className="mx-auto max-w-6xl">
        <header className="mb-5 flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-2xl border border-white/15 bg-[linear-gradient(140deg,#3b82f6,#8b5cf6)] shadow-[0_8px_22px_rgba(59,130,246,0.35),inset_0_1px_0_rgba(255,255,255,0.3)]">
            <Radar size={19} className="text-white" />
          </div>
          <div className="min-w-0">
            <h1 className="text-xl font-semibold tracking-tight text-[var(--as-text-bright)]">事件钩子</h1>
            <p className="text-xs text-[var(--as-text-muted)]">盯住不确定性 · 重大才打扰</p>
          </div>
          <span className="ml-auto inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.05] px-2.5 py-1 text-[11px] text-[var(--as-text-secondary)]">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.7)]" />
            实时监控
          </span>
        </header>

        {usingMock ? <Banner tone="amber">演示数据模式（VITE_HOOKS_MOCK=1）：以下为本地示例，改动仅存内存、不落库。关闭该开关即接入实时后端。</Banner> : null}
        {error ? <Banner tone="rose">{error}</Banner> : null}
        {scanNote ? <Banner tone="sky">{scanNote}</Banner> : null}

        <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
          {loading && !summaries.length ? (
            <div className="as-glass h-40 animate-pulse rounded-2xl" />
          ) : (
            <HookList summaries={summaries} currentId={currentId} onSelect={selectHook} onCreate={() => setForm({ mode: "new" })} />
          )}
          <HookDetail summary={current} usingMock={usingMock} scanningId={scanningId} onRun={runHook} onEdit={onEdit} onDelete={onDelete} />
        </div>
      </div>
      {form ? <HookForm initial={form.mode === "edit" ? form.summary : null} onClose={() => setForm(null)} onSubmit={onSubmit} /> : null}
    </div>
  );
}

const TONES: Record<string, string> = {
  amber: "border-amber-400/25 bg-amber-500/10 text-amber-200",
  rose: "border-rose-400/25 bg-rose-500/10 text-rose-200",
  sky: "border-sky-400/25 bg-sky-500/10 text-sky-200",
};

function Banner({ tone, children }: { tone: keyof typeof TONES; children: React.ReactNode }) {
  return <div className={`mb-4 rounded-xl border px-3.5 py-2.5 text-xs ${TONES[tone]}`}>{children}</div>;
}
