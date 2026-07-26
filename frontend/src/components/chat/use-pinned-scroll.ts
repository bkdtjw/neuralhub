import { type RefObject, useRef, useState } from "react";

import { PINNED_THRESHOLD_PX } from "@/components/chat/auto-scroll";

interface PinnedScroll {
  pinned: boolean;
  /** 供吸底 effect 同步读取，避免 state 闭包滞后。 */
  pinnedRef: RefObject<boolean>;
  handleScroll: () => void;
  scrollToBottom: () => void;
}

/**
 * 贴底（pinned）状态管理：滚动时按距底阈值更新；点击「回到底部」后
 * 平滑滚动途中仍未贴底，短暂忽略以免浮钮闪现。
 */
export function usePinnedScroll(
  containerRef: RefObject<HTMLDivElement | null>,
  endRef: RefObject<HTMLDivElement | null>,
): PinnedScroll {
  const pinnedRef = useRef(true);
  const suppressUnpinUntilRef = useRef(0);
  const [pinned, setPinned] = useState(true);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < PINNED_THRESHOLD_PX;
    if (!nearBottom && Date.now() < suppressUnpinUntilRef.current) return;
    pinnedRef.current = nearBottom;
    setPinned(nearBottom);
  };

  const scrollToBottom = () => {
    suppressUnpinUntilRef.current = Date.now() + 800;
    pinnedRef.current = true;
    setPinned(true);
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  };

  return { pinned, pinnedRef, handleScroll, scrollToBottom };
}
