import LoadingDots from "@/components/common/LoadingDots";

/** 懒加载路由的玻璃风居中占位：仅在 chunk 下载期间短暂可见。 */
export default function RouteLoading() {
  return (
    <div className="flex h-full items-center justify-center">
      <div
        className="as-glass flex items-center gap-3 rounded-2xl px-6 py-4 text-sm text-[var(--as-text-muted)]"
        role="status"
        aria-live="polite"
      >
        <LoadingDots />
        <span>页面加载中…</span>
      </div>
    </div>
  );
}
