import { describe, expect, it } from "vitest";

import { PINNED_THRESHOLD_PX, shouldAutoScroll } from "@/components/chat/auto-scroll";
import type { Message } from "@/types";

const msg = (id: string, role: Message["role"]): Message => ({
  id,
  role,
  content: "",
  timestamp: "t",
});

describe("shouldAutoScroll（F5：条件吸底）", () => {
  it("用户主动发送新消息（末条新增为 user）时无条件吸底，即使未贴底", () => {
    const prev = [msg("a", "assistant")];
    const next = [msg("a", "assistant"), msg("b", "user")];
    expect(shouldAutoScroll(prev, next, false)).toBe(true);
  });

  it("从空会话发出首条 user 消息也无条件吸底", () => {
    expect(shouldAutoScroll([], [msg("a", "user")], false)).toBe(true);
  });

  it("token 追加（消息数不变）时未贴底则不吸底（不打断向上翻阅）", () => {
    const list = [msg("a", "user"), msg("b", "assistant")];
    expect(shouldAutoScroll(list, list, false)).toBe(false);
  });

  it("token 追加（消息数不变）时已贴底则跟随吸底", () => {
    const list = [msg("a", "user"), msg("b", "assistant")];
    expect(shouldAutoScroll(list, list, true)).toBe(true);
  });

  it("流式结束追加 assistant 消息时未贴底不吸底", () => {
    const prev = [msg("a", "user")];
    const next = [msg("a", "user"), msg("b", "assistant")];
    expect(shouldAutoScroll(prev, next, false)).toBe(false);
  });

  it("流式结束追加 assistant 消息时已贴底则吸底", () => {
    const prev = [msg("a", "user")];
    const next = [msg("a", "user"), msg("b", "assistant")];
    expect(shouldAutoScroll(prev, next, true)).toBe(true);
  });

  it("导出贴底阈值常量供滚动容器复用", () => {
    expect(PINNED_THRESHOLD_PX).toBe(80);
  });
});
