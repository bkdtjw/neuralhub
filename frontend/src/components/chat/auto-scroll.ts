import type { Message } from "@/types";

// 距底小于该像素数即视为“贴底”，此时新内容才自动吸底。
export const PINNED_THRESHOLD_PX = 80;

/**
 * 判断消息列表是否应自动吸底。
 * - 用户主动发送新消息（末条为新增的 user 消息）时无条件吸底；
 * - 其余情况（token 追加、状态变化、审批出现等）仅在用户已贴近底部时吸底，
 *   避免向上翻阅历史时被强行拽回底部。
 */
export const shouldAutoScroll = (prev: Message[], next: Message[], isPinned: boolean): boolean => {
  const appendedUserMessage = next.length > prev.length && next[next.length - 1]?.role === "user";
  return appendedUserMessage || isPinned;
};
