import { type KeyboardEvent, useState } from "react";
import { X } from "lucide-react";

interface TagInputProps {
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  prefix?: string; // 例如博主输入显示 "@"
}

export default function TagInput({ values, onChange, placeholder, prefix }: TagInputProps) {
  const [draft, setDraft] = useState("");

  const add = (raw: string) => {
    const value = raw.trim().replace(/^@+/, "");
    if (!value || values.includes(value)) return;
    onChange([...values, value]);
  };

  const commit = () => {
    add(draft);
    setDraft("");
  };

  const onKey = (event: KeyboardEvent<HTMLInputElement>) => {
    // IME 组词中（拼音候选未确认）：放行本次 keydown，交给输入法确认候选词，
    // 绝不 preventDefault / commit，否则会吞掉选词并把半成品拼音提交成 tag。
    if (event.nativeEvent.isComposing || event.key === "Process") return;
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      commit();
    } else if (event.key === "Backspace" && !draft && values.length) {
      onChange(values.slice(0, -1));
    }
  };

  return (
    <div className="as-glass-input flex min-h-[40px] flex-wrap items-center gap-1.5 rounded-xl px-2 py-1.5">
      {values.map((value) => (
        <span
          key={value}
          className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/10 px-2 py-0.5 text-xs text-[var(--as-text)]"
        >
          {prefix}
          {value}
          <button
            type="button"
            onClick={() => onChange(values.filter((item) => item !== value))}
            className="text-[var(--as-text-muted)] transition-colors hover:text-[var(--as-text)]"
          >
            <X size={12} />
          </button>
        </span>
      ))}
      <input
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={onKey}
        onBlur={commit}
        placeholder={values.length ? "" : placeholder}
        className="min-w-[90px] flex-1 bg-transparent text-sm text-[var(--as-text)] outline-none placeholder:text-[var(--as-text-muted)]"
      />
    </div>
  );
}
