interface CacheHitTrendProps {
  labels: string[];
  hitTokens: number[];
  missTokens: number[];
}

const formatCompact = (value: number) =>
  value >= 1000 ? `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}K` : String(value);

const maxValue = (values: number[]) => values.reduce((current, value) => Math.max(current, value), 0);

// 一根柱 = 当日 LLM 输入 token：底段金色为命中缓存(cache_read)，顶段灰色为未命中
// (未走缓存的输入 + 首写缓存)。命中率 = 命中 ÷ (命中 + 未命中)，标注在日期下方。
export default function CacheHitTrend({ labels, hitTokens, missTokens }: CacheHitTrendProps) {
  const totals = labels.map((_, index) => (hitTokens[index] ?? 0) + (missTokens[index] ?? 0));
  const max = Math.max(maxValue(totals), 1);

  return (
    <section className="rounded-3xl border border-[#252525] bg-[#0b0b0b] p-5">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium text-[#f0f6fc]">每日趋势 · Token 缓存</h3>
        <div className="flex gap-4 text-xs text-[#7d8590]">
          <span className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-[3px] bg-[#d29922]" />
            命中缓存
          </span>
          <span className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-[3px] bg-[#6e7681]" />
            未命中
          </span>
        </div>
      </div>

      <div className="mt-6 overflow-x-auto">
        <div className="grid min-w-max auto-cols-[64px] grid-flow-col gap-3">
          {labels.map((label, index) => {
            const hit = hitTokens[index] ?? 0;
            const miss = missTokens[index] ?? 0;
            const total = hit + miss;
            const rate = total > 0 ? Math.round((hit / total) * 100) : null;
            // 97% 封顶：最高柱 + 2px 段间缝隙不溢出胶囊内容区。
            const hitHeight = `${Math.max((hit / max) * 97, hit > 0 ? 2 : 0)}%`;
            const missHeight = `${Math.max((miss / max) * 97, miss > 0 ? 2 : 0)}%`;
            const detail = [
              `总输入 ${formatCompact(total)}`,
              `命中 ${formatCompact(hit)}`,
              `未命中 ${formatCompact(miss)}`,
              rate === null ? "" : `命中率 ${rate}%`,
            ]
              .filter(Boolean)
              .join(" · ");

            return (
              <div key={label} className="flex min-w-0 flex-col items-center gap-3">
                <div
                  className="flex h-44 w-full flex-col items-center justify-end rounded-2xl border border-[#1b1b1b] bg-[#090909] px-3 py-4"
                  title={detail}
                >
                  {miss > 0 ? (
                    <div className="w-[18px] rounded-t-[4px] bg-[#6e7681] transition-all" style={{ height: missHeight }} />
                  ) : null}
                  {hit > 0 && miss > 0 ? <div className="h-[2px] w-[18px] shrink-0" /> : null}
                  {hit > 0 ? (
                    <div
                      className={`w-[18px] bg-[#d29922] transition-all${miss > 0 ? "" : " rounded-t-[4px]"}`}
                      style={{ height: hitHeight }}
                    />
                  ) : null}
                </div>
                <div className="text-center text-xs text-[#7d8590]">
                  <div>{label.slice(5)}</div>
                  <div className="mt-1 text-[11px] text-[#4f5964]">{rate === null ? "—" : `${rate}%`}</div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
