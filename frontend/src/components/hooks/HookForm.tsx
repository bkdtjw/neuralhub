import { type FormEvent, useState } from "react";
import { X } from "lucide-react";

import TagInput from "@/components/hooks/TagInput";
import { Choice, Field } from "@/components/hooks/HookFormFields";
import type { HookDraft, HookSources, HookSummary } from "@/types/hooks";

const DEFAULT_DRAFT: HookDraft = {
  name: "",
  twitter: { accounts: [], keywords: [] },
  sources: { twitter: true, exaWeb: true, zhipuSearch: false, youtube: false },
  cadenceMinutes: 40,
  materiality: 60,
  enabled: true,
};

const CADENCE_PRESETS = [
  { label: "高频", hint: "10 分钟", value: 10 },
  { label: "常规", hint: "40 分钟", value: 40 },
  { label: "低频", hint: "3 小时", value: 180 },
];

const MATERIALITY_PRESETS = [
  { label: "只报大事", hint: "高门槛", value: 75 },
  { label: "适中", hint: "推荐", value: 60 },
  { label: "什么都要", hint: "灵敏", value: 40 },
];

// muted：当前后端尚无检索实现，诚实标注"（未接入）"但不禁用（后端仍接受该配置）。
const SOURCE_KEYS: { key: keyof HookSources; label: string; muted?: boolean }[] = [
  { key: "twitter", label: "X 推文" },
  { key: "exaWeb", label: "Exa 权威确认" },
  { key: "zhipuSearch", label: "智谱中文网搜（未接入）", muted: true },
  { key: "youtube", label: "YouTube（未接入）", muted: true },
];

// 账号与后端一致地归一（去 @ 已在 TagInput 内做），关键词字段不传保持原样。
const lower = (value: string): string => value.toLowerCase();

const fromSummary = (summary: HookSummary): HookDraft => ({
  name: summary.hook.name,
  twitter: { accounts: [...summary.hook.twitter.accounts], keywords: [...summary.hook.twitter.keywords] },
  sources: { ...summary.hook.sources },
  cadenceMinutes: summary.hook.cadenceMinutes,
  materiality: summary.hook.materiality,
  enabled: summary.hook.enabled,
});

interface HookFormProps {
  initial: HookSummary | null;
  onClose: () => void;
  onSubmit: (draft: HookDraft) => Promise<void>;
}

export default function HookForm({ initial, onClose, onSubmit }: HookFormProps) {
  const [draft, setDraft] = useState<HookDraft>(initial ? fromSummary(initial) : DEFAULT_DRAFT);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const patch = (part: Partial<HookDraft>) => setDraft((current) => ({ ...current, ...part }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!draft.name.trim()) {
      setError("给钩子起个名字");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await onSubmit({ ...draft, name: draft.name.trim() });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4" onClick={onClose}>
      <form
        onClick={(event) => event.stopPropagation()}
        onSubmit={submit}
        className="as-glass max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl p-5"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold text-[var(--as-text-bright)]">{initial ? "编辑钩子" : "新建钩子"}</h2>
          <button
            type="button"
            onClick={onClose}
            className="grid h-7 w-7 place-items-center rounded-lg text-[var(--as-text-muted)] transition-colors hover:bg-white/10 hover:text-[var(--as-text)]"
          >
            <X size={16} />
          </button>
        </div>

        <Field label="名称">
          <input
            value={draft.name}
            onChange={(event) => patch({ name: event.target.value })}
            placeholder="例如：Fable 5 回归追踪"
            className="as-glass-input h-10 w-full rounded-xl px-3 text-sm"
            autoFocus
          />
        </Field>

        <Field label="盯的博主" hint="推特 handle，回车添加；可信博主随手加">
          <TagInput
            values={draft.twitter.accounts}
            onChange={(accounts) => patch({ twitter: { ...draft.twitter, accounts } })}
            placeholder="polymarket、anthropicai…"
            prefix="@"
            normalize={lower}
          />
        </Field>

        <Field label="话题词" hint="高门槛触发，缩小到这个事件">
          <TagInput
            values={draft.twitter.keywords}
            onChange={(keywords) => patch({ twitter: { ...draft.twitter, keywords } })}
            placeholder="Fable 5、解禁…"
          />
        </Field>

        <Field label="补充数据源">
          <div className="flex flex-wrap gap-2">
            {SOURCE_KEYS.map(({ key, label, muted }) => {
              const on = draft.sources[key];
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => patch({ sources: { ...draft.sources, [key]: !on } })}
                  title={muted ? "当前无检索实现，配置会保存但暂不生效" : undefined}
                  className={`rounded-[10px] border px-3 py-1.5 text-xs transition-colors duration-150 ${
                    on ? "border-sky-400/40 bg-sky-500/20 text-sky-100" : "border-white/10 bg-white/[0.03] text-[var(--as-text-muted)] hover:bg-white/[0.06]"
                  } ${muted && !on ? "opacity-60" : ""}`}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </Field>

        <Field label="扫描节奏" hint="多久自动扫一次">
          <Choice
            options={CADENCE_PRESETS}
            value={draft.cadenceMinutes}
            onPick={(value) => patch({ cadenceMinutes: value })}
            currentLabel={(v) => `当前 ${v} 分钟`}
          />
        </Field>

        <Field label="打扰门槛" hint="越过门槛才推飞书，平时只进看板">
          <Choice
            options={MATERIALITY_PRESETS}
            value={draft.materiality}
            onPick={(value) => patch({ materiality: value })}
            currentLabel={(v) => `当前 ${v}`}
          />
        </Field>

        <label className="mb-4 flex cursor-pointer items-center gap-2.5 rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2.5 text-sm text-[var(--as-text-secondary)]">
          <input type="checkbox" checked={draft.enabled} onChange={(event) => patch({ enabled: event.target.checked })} className="accent-sky-500" />
          启用（关闭则暂停扫描）
        </label>

        {error ? <div className="mb-3 rounded-xl border border-rose-400/25 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">{error}</div> : null}

        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="as-glass-btn h-9 rounded-[10px] px-4 text-sm">
            取消
          </button>
          <button type="submit" disabled={busy} className="as-glass-accent h-9 rounded-[10px] px-4 text-sm font-medium">
            {busy ? "保存中" : "保存"}
          </button>
        </div>
      </form>
    </div>
  );
}
