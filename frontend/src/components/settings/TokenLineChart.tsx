import { useState } from "react";

import type { TokenUsageDay } from "@/types";
import { formatTokens, formatTokensExact, shortDate } from "@/components/settings/token-usage-utils";

interface TokenLineChartProps {
  days: TokenUsageDay[];
}

const WIDTH = 720;
const HEIGHT = 180;
const PAD_LEFT = 44;
const PAD_BOTTOM = 22;
const PAD_TOP = 8;

const buildPath = (values: number[], xOf: (index: number) => number, yOf: (value: number) => number): string =>
  values.map((value, index) => `${index === 0 ? "M" : "L"}${xOf(index).toFixed(1)},${yOf(value).toFixed(1)}`).join(" ");

export default function TokenLineChart({ days }: TokenLineChartProps) {
  const [hover, setHover] = useState<number | null>(null);
  if (days.length < 2) return null;

  const max = Math.max(...days.map((item) => Math.max(item.promptTokens, item.completionTokens)), 1);
  const plotWidth = WIDTH - PAD_LEFT;
  const plotHeight = HEIGHT - PAD_BOTTOM - PAD_TOP;
  const xOf = (index: number) => PAD_LEFT + (plotWidth * index) / (days.length - 1);
  const yOf = (value: number) => PAD_TOP + plotHeight * (1 - value / max);
  const labelEvery = Math.max(1, Math.ceil(days.length / 8));
  const hovered = hover !== null ? days[hover] : null;
  const tooltipLeftPct = hover !== null ? Math.min(Math.max((xOf(hover) / WIDTH) * 100, 14), 86) : 0;

  const handleMove = (event: React.MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * WIDTH;
    const index = Math.round(((x - PAD_LEFT) / plotWidth) * (days.length - 1));
    setHover(Math.min(Math.max(index, 0), days.length - 1));
  };

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full" onMouseMove={handleMove} onMouseLeave={() => setHover(null)}>
        {[0.5, 1].map((ratio) => (
          <g key={ratio}>
            <line x1={PAD_LEFT} x2={WIDTH} y1={yOf(max * ratio)} y2={yOf(max * ratio)} stroke="var(--as-border)" strokeDasharray="4 4" />
            <text x={PAD_LEFT - 6} y={yOf(max * ratio) + 4} textAnchor="end" fontSize="10" fill="var(--as-text-muted)">
              {formatTokens(max * ratio)}
            </text>
          </g>
        ))}
        <line x1={PAD_LEFT} x2={WIDTH} y1={yOf(0)} y2={yOf(0)} stroke="var(--as-border-strong)" />
        <path d={`${buildPath(days.map((item) => item.promptTokens), xOf, yOf)} L${xOf(days.length - 1)},${yOf(0)} L${xOf(0)},${yOf(0)} Z`} fill="#3b82f6" opacity="0.12" />
        <path d={buildPath(days.map((item) => item.promptTokens), xOf, yOf)} fill="none" stroke="#3b82f6" strokeWidth="2" strokeLinejoin="round" />
        <path d={buildPath(days.map((item) => item.completionTokens), xOf, yOf)} fill="none" stroke="#8b5cf6" strokeWidth="2" strokeLinejoin="round" />
        {days.map((item, index) =>
          index % labelEvery === 0 ? (
            <text key={item.date} x={xOf(index)} y={HEIGHT - 6} textAnchor="middle" fontSize="10" fill="var(--as-text-muted)">
              {shortDate(item.date)}
            </text>
          ) : null,
        )}
        {hover !== null && hovered ? (
          <g pointerEvents="none">
            <line x1={xOf(hover)} x2={xOf(hover)} y1={PAD_TOP} y2={yOf(0)} stroke="var(--as-text-muted)" strokeDasharray="3 3" />
            <circle cx={xOf(hover)} cy={yOf(hovered.promptTokens)} r="3.5" fill="#3b82f6" />
            <circle cx={xOf(hover)} cy={yOf(hovered.completionTokens)} r="3.5" fill="#8b5cf6" />
          </g>
        ) : null}
      </svg>
      {hovered ? (
        <div
          className="pointer-events-none absolute top-1 z-10 -translate-x-1/2 rounded-lg border border-[var(--as-border-strong)] bg-[var(--as-surface-raised)] px-3 py-2 text-xs shadow-xl"
          style={{ left: `${tooltipLeftPct}%` }}
        >
          <div className="font-medium text-[var(--as-text)]">{hovered.date}</div>
          <div className="mt-1 space-y-0.5 text-[var(--as-text-secondary)]">
            <div><span className="text-[#3b82f6]">输入</span> <span className="font-mono text-[var(--as-text)]">{formatTokensExact(hovered.promptTokens)}</span></div>
            <div><span className="text-[#8b5cf6]">输出</span> <span className="font-mono text-[var(--as-text)]">{formatTokensExact(hovered.completionTokens)}</span></div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
