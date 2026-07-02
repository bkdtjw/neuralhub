// HookForm 的展示型子组件（玻璃风）：字段容器 Field 与三档单选 Choice。
// 从 HookForm.tsx 拆出以守住单文件 ≤200 行；无自身状态，纯受控渲染。
import type { ReactNode } from "react";

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="mb-4">
      <div className="mb-1.5 flex items-baseline gap-2">
        <span className="text-sm text-[var(--as-text)]">{label}</span>
        {hint ? <span className="text-[11px] text-[var(--as-text-muted)]">{hint}</span> : null}
      </div>
      {children}
    </div>
  );
}

export function Choice({
  options,
  value,
  onPick,
  currentLabel,
}: {
  options: { label: string; hint: string; value: number }[];
  value: number;
  onPick: (value: number) => void;
  // 当前值不在任一预设档时，用它渲染只读高亮 chip，确保当前值永远可见。
  currentLabel?: (value: number) => string;
}) {
  const inPresets = options.some((option) => option.value === value);
  return (
    <div className="grid grid-cols-3 gap-2">
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onPick(option.value)}
            className={`rounded-xl border px-2 py-2 text-center transition-colors duration-150 ${
              active ? "border-sky-400/40 bg-sky-500/15" : "border-white/8 bg-white/[0.03] hover:bg-white/[0.06]"
            }`}
          >
            <div className={`text-xs ${active ? "text-sky-100" : "text-[var(--as-text)]"}`}>{option.label}</div>
            <div className="text-[10px] text-[var(--as-text-muted)]">{option.hint}</div>
          </button>
        );
      })}
      {!inPresets && currentLabel ? (
        <button
          type="button"
          onClick={() => onPick(value)}
          title="当前值不在预设档，点击保持不变"
          className="col-span-3 rounded-xl border border-amber-400/40 bg-amber-500/15 px-2 py-1.5 text-center"
        >
          <div className="text-xs text-amber-100">{currentLabel(value)}</div>
          <div className="text-[10px] text-amber-200/60">当前值 · 点上方任一档可切换</div>
        </button>
      ) : null}
    </div>
  );
}
