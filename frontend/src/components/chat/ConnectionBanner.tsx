export default function ConnectionBanner({ state, onReconnect }: { state: "reconnecting" | "disconnected"; onReconnect: () => void }) {
  const reconnecting = state === "reconnecting";
  return (
    <div className="flex shrink-0 items-center justify-center gap-2.5 border-b border-[var(--as-border)] bg-[var(--as-surface)] px-5 py-1.5 text-[12px]">
      <span className={`h-1.5 w-1.5 rounded-full bg-[var(--as-danger)] ${reconnecting ? "animate-pulse" : ""}`} />
      <span className="text-[var(--as-text-secondary)]">{reconnecting ? "连接已断开，正在重连…" : "连接已断开"}</span>
      {reconnecting ? null : (
        <button
          type="button"
          onClick={onReconnect}
          className="rounded-md border border-[var(--as-border-strong)] bg-[var(--as-bg)] px-2 py-0.5 text-[11px] text-[var(--as-text)] transition hover:border-[var(--as-accent)] hover:text-[var(--as-accent-soft)]"
        >
          点击重连
        </button>
      )}
    </div>
  );
}
