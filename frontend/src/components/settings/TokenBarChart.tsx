import { useState } from "react";

import type { TokenUsageDay } from "@/types";
import { formatTokens, formatTokensExact, shortDate } from "@/components/settings/token-usage-utils";
import type { DayAggregates } from "@/components/settings/token-usage-utils";

interface TokenBarChartProps {
  days: TokenUsageDay[];
  aggregates: Map<string, DayAggregates>;
}

const WIDTH = 720;
const HEIGHT = 200;
const PAD_LEFT = 44;
const PAD_BOTTOM = 22;
const PAD_TOP = 8;

export default function TokenBarChart({ days, aggregates }: TokenBarChartProps) {
  const [hover, setHover] = useState<number | null>(null);
  if (!days.length) return null;

  const max = Math.max(...days.map((item) => item.totalTokens), 1);
  const plotWidth = WIDTH - PAD_LEFT;
  const plotHeight = HEIGHT - PAD_BOTTOM - PAD_TOP;
  const step = plotWidth / days.length;
  const barWidth = Math.max(Math.min(step * 0.66, 26), 2);
  const yOf = (value: number) => PAD_TOP + plotHeight * (1 - value / max);
  const labelEvery = Math.max(1, Math.ceil(days.length / 8));
  const hovered = hover !== null ? days[hover] : null;
  const hoveredAgg = hovered ? aggregates.get(hovered.date) : undefined;
  const tooltipLeftPct = hover !== null ? Math.min(Math.max(((PAD_LEFT + step * (hover + 0.5)) / WIDTH) * 100, 14), 86) : 0;

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full" onMouseLeave={() => setHover(null)}>
        {[0.5, 1].map((ratio) => (
          <g key={ratio}>
            <line x1={PAD_LEFT} x2={WIDTH} y1={yOf(max * ratio)} y2={yOf(max * ratio)} stroke="var(--as-border)" strokeDasharray="4 4" />
            <text x={PAD_LEFT - 6} y={yOf(max * ratio) + 4} textAnchor="end" fontSize="10" fill="var(--as-text-muted)">
              {formatTokens(max * ratio)}
            </text>
          </g>
        ))}
        <line x1={PAD_LEFT} x2={WIDTH} y1={yOf(0)} y2={yOf(0)} stroke="var(--as-border-strong)" />
        {days.map((item, index) => {
          const x = PAD_LEFT + step * index + (step - barWidth) / 2;
          const promptY = yOf(item.promptTokens);
          const totalY = yOf(item.totalTokens);
          const active = hover === index;
          return (
            <g key={item.date}>
              {/* prompt 段（下）+ completion 段（上）堆叠 */}
              <rect x={x} y={promptY} width={barWidth} height={Math.max(yOf(0) - promptY, 0)} rx="2" fill="#3b82f6" opacity={active ? 1 : 0.75} />
              <rect x={x} y={totalY} width={barWidth} height={Math.max(promptY - totalY, 0)} rx="2" fill="#8b5cf6" opacity={active ? 1 : 0.75} />
              <rect
                x={PAD_LEFT + step * index}
                y={PAD_TOP}
                width={step}
                height={plotHeight}
                fill="transparent"
                onMouseEnter={() => setHover(index)}
              />
              {index % labelEvery === 0 ? (
                <text x={PAD_LEFT + step * (index + 0.5)} y={HEIGHT - 6} textAnchor="middle" fontSize="10" fill="var(--as-text-muted)">
                  {shortDate(item.date)}
                </text>
              ) : null}
            </g>
          );
        })}
        {hover !== null ? (
          <line
            x1={PAD_LEFT + step * (hover + 0.5)}
            x2={PAD_LEFT + step * (hover + 0.5)}
            y1={PAD_TOP}
            y2={yOf(0)}
            stroke="var(--as-text-muted)"
            strokeDasharray="3 3"
            pointerEvents="none"
          />
        ) : null}
      </svg>
      {hovered ? (
        <div
          className="pointer-events-none absolute top-1 z-10 -translate-x-1/2 rounded-lg border border-[var(--as-border-strong)] bg-[var(--as-surface-raised)] px-3 py-2 text-xs shadow-xl"
          style={{ left: `${tooltipLeftPct}%` }}
        >
          <div className="font-medium text-[var(--as-text)]">{hovered.date}</div>
          <div className="mt-1 space-y-0.5 text-[var(--as-text-secondary)]">
            <div>当天 <span className="font-mono text-[var(--as-text)]">{formatTokensExact(hovered.totalTokens)}</span></div>
            <div className="text-[11px]">
              <span className="text-[#3b82f6]">输入 {formatTokens(hovered.promptTokens)}</span>
              {" · "}
              <span className="text-[#8b5cf6]">输出 {formatTokens(hovered.completionTokens)}</span>
              {" · "}调用 {hovered.llmCalls} 次
            </div>
            <div>本周 <span className="font-mono text-[var(--as-text)]">{formatTokensExact(hoveredAgg?.weekTotal ?? 0)}</span></div>
            <div>本月 <span className="font-mono text-[var(--as-text)]">{formatTokensExact(hoveredAgg?.monthTotal ?? 0)}</span></div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
