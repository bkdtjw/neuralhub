import { ArrowDown } from "lucide-react";

interface ScrollToBottomButtonProps {
  visible: boolean;
  /** 流式生成中有新内容时，按钮上叠一个脉冲点提示。 */
  hasNew: boolean;
  onClick: () => void;
}

/** 非贴底时浮在消息区右下角的「回到底部」玻璃圆钮。 */
export default function ScrollToBottomButton({ visible, hasNew, onClick }: ScrollToBottomButtonProps) {
  if (!visible) return null;
  return (
    <button
      type="button"
      onClick={onClick}
      title="回到底部"
      aria-label="回到底部"
      className="as-glass absolute bottom-[232px] right-6 z-10 flex h-9 w-9 items-center justify-center rounded-full text-[var(--as-text-secondary)] transition hover:text-[var(--as-text)]"
    >
      <ArrowDown size={16} />
      {hasNew ? (
        <span className="absolute -right-0.5 -top-0.5 h-2 w-2 animate-pulse rounded-full bg-[var(--as-accent)]" aria-hidden />
      ) : null}
    </button>
  );
}
