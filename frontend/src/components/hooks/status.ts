// 钩子状态 / 数据源的展示文案与配色（前端共享，玻璃风）。
import type { HookStatus } from "@/types/hooks";

export const STATUS_LABEL: Record<HookStatus, string> = {
  developing: "发展中",
  stable: "平稳",
  escalating: "升级中",
  resolved: "已收尾",
};

export const STATUS_CLASS: Record<HookStatus, string> = {
  escalating: "border border-rose-400/30 bg-rose-500/15 text-rose-200",
  developing: "border border-sky-400/30 bg-sky-500/15 text-sky-200",
  stable: "border border-slate-400/25 bg-slate-400/10 text-slate-200",
  resolved: "border border-emerald-400/30 bg-emerald-500/15 text-emerald-200",
};

export const STATUS_DOT: Record<HookStatus, string> = {
  escalating: "bg-rose-400 shadow-[0_0_9px_rgba(251,113,133,0.75)]",
  developing: "bg-sky-400 shadow-[0_0_9px_rgba(56,189,248,0.6)]",
  stable: "bg-slate-400",
  resolved: "bg-emerald-400 shadow-[0_0_9px_rgba(52,211,153,0.6)]",
};

const SOURCE_LABEL: Record<string, string> = {
  twitter: "X",
  exa: "Exa",
  zhipu: "智谱",
  youtube: "油管",
};

export const sourceLabel = (source: string): string => SOURCE_LABEL[source] ?? source;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Twitter legacy 时间串（如 "Fri Jun 27 09:12:00 +0000 2026"）在 Safari/Firefox 的
// new Date() 返回 Invalid Date。纯函数解析：月名映射 + 时区偏移 → UTC epoch(ms)；
// 不匹配返回 null，交由调用方兜底。
const parseLegacyTwitter = (ts: string): number | null => {
  const m = ts.match(/^\w{3} (\w{3}) (\d{2}) (\d{2}):(\d{2}):(\d{2}) ([+-]\d{4}) (\d{4})$/);
  if (!m) return null;
  const month = MONTHS.indexOf(m[1]);
  if (month < 0) return null;
  const [, , day, hh, mm, ss, tz, year] = m;
  const offsetMin = (tz[0] === "-" ? -1 : 1) * (Number(tz.slice(1, 3)) * 60 + Number(tz.slice(3, 5)));
  const utc = Date.UTC(Number(year), month, Number(day), Number(hh), Number(mm), Number(ss));
  return utc - offsetMin * 60_000; // 减去偏移得到真正的 UTC 时刻
};

// "2026-06-27T09:12:00Z" → "06-27 17:12"（本地时区）；兼容 Twitter legacy 串；仍失败原样返回。
export const formatTs = (ts: string): string => {
  if (!ts) return "—";
  let date = new Date(ts);
  if (Number.isNaN(date.getTime())) {
    const legacy = parseLegacyTwitter(ts);
    if (legacy === null) return ts;
    date = new Date(legacy);
  }
  const pad = (n: number): string => String(n).padStart(2, "0");
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
};
