// 指标页首载骨架：卡片栅格 + 两块趋势图占位（配色沿用 Metrics 页独立深色皮肤）。
export default function MetricsSkeleton() {
  return (
    <>
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }, (_, index) => (
          <div key={index} className="h-[136px] animate-pulse rounded-2xl border border-[#252525] bg-[#101010]" />
        ))}
      </section>
      <div className="h-[300px] animate-pulse rounded-3xl border border-[#252525] bg-[#101010]" />
      <div className="h-[300px] animate-pulse rounded-3xl border border-[#252525] bg-[#101010]" />
    </>
  );
}
