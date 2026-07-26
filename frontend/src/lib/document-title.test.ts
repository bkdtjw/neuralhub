import { afterEach, describe, expect, it } from "vitest";

import { clearDone, flagDone, setBaseTitle } from "@/lib/document-title";

describe("document-title", () => {
  afterEach(() => {
    clearDone();
    setBaseTitle("NeuralHub");
  });

  it("setBaseTitle 直接写入 document.title，空串回退默认", () => {
    setBaseTitle("新线程 - NeuralHub");
    expect(document.title).toBe("新线程 - NeuralHub");
    setBaseTitle("   ");
    expect(document.title).toBe("NeuralHub");
  });

  it("flagDone 加前缀且幂等，clearDone 恢复基础标题", () => {
    setBaseTitle("指标 - NeuralHub");
    flagDone();
    flagDone();
    expect(document.title).toBe("✓ 已完成 指标 - NeuralHub");
    clearDone();
    expect(document.title).toBe("指标 - NeuralHub");
  });

  it("标记期间 setBaseTitle 保留前缀，回前台自动清除", () => {
    setBaseTitle("会话A - NeuralHub");
    flagDone();
    setBaseTitle("会话B - NeuralHub");
    expect(document.title).toBe("✓ 已完成 会话B - NeuralHub");
    // jsdom 默认 document.hidden=false，派发 visibilitychange 即模拟“回到前台”。
    document.dispatchEvent(new Event("visibilitychange"));
    expect(document.title).toBe("会话B - NeuralHub");
  });
});
