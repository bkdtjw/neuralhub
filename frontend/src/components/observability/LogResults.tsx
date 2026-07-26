import { useState } from "react";

import type { LogEntry } from "@/types";

interface LogResultsProps {
  logs: LogEntry[];
  title: string;
  searched: boolean;
}

const levelTone: Record<LogEntry["level"], string> = {
  debug: "text-[#7d8590]",
  info: "text-[#e6edf3]",
  warning: "text-[#d29922]",
  error: "text-[#ff7b72]",
};

const formatTime = (value: string) =>
  new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));

export default function LogResults({ logs, title, searched }: LogResultsProps) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (logs.length === 0) {
    return (
      <section className="rounded-3xl border border-dashed border-[#2c2c2c] bg-[#050505] p-6 text-sm text-[#7d8590]">
        {searched ? "暂无匹配日志。" : "输入 trace_id / session_id 或筛选条件，开始检索日志。"}
      </section>
    );
  }

  return (
    <section className="rounded-3xl border border-[#252525] bg-[#0b0b0b] p-5">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium text-[#f0f6fc]">{title}</h3>
        <span className="text-sm text-[#7d8590]">{logs.length} 条</span>
      </div>

      <div className="mt-4 space-y-2">
        {logs.map((entry) => {
          const key = `${entry.timestamp}-${entry.event}-${entry.workerId}`;
          const isOpen = expanded === key;

          return (
            <article key={key} className="overflow-hidden rounded-2xl border border-[#1f1f1f] bg-[#070707]">
              <button
                type="button"
                onClick={() => setExpanded(isOpen ? null : key)}
                className="grid w-full grid-cols-[90px_70px_minmax(0,1fr)_120px] items-center gap-3 px-4 py-3 text-left text-sm hover:bg-[#111111]"
              >
                <span className="text-[#7d8590]">{formatTime(entry.timestamp)}</span>
                <span className={levelTone[entry.level]}>{entry.level}</span>
                <span className="truncate text-[#f0f6fc]">{entry.event}</span>
                <span className="truncate text-right text-[#7d8590]">{entry.traceId || "-"}</span>
              </button>

              {isOpen ? (
                <pre className="overflow-x-auto border-t border-[#1f1f1f] bg-[#040404] px-4 py-4 text-xs leading-6 text-[#9fb3c8]">
                  {JSON.stringify(entry, null, 2)}
                </pre>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}
