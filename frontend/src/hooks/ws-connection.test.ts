import { beforeEach, describe, expect, it, vi } from "vitest";

import { createConnectionHandlers } from "@/hooks/ws-connection";
import { api } from "@/lib/api-client";
import { useSessionStore } from "@/stores/sessionStore";

describe("ws-connection handlers（F4：连接事件 → connectionState / resync）", () => {
  beforeEach(() => {
    useSessionStore.setState({ connectionState: "connected", currentSessionId: "s1", messages: [] });
  });

  it("onClose 置 reconnecting；已 disconnected 时保持（give-up 后不闪回、手动重连入口不消失）", () => {
    const { onClose } = createConnectionHandlers("s1");
    useSessionStore.setState({ connectionState: "connected" });
    onClose();
    expect(useSessionStore.getState().connectionState).toBe("reconnecting");
    useSessionStore.setState({ connectionState: "disconnected" });
    onClose();
    expect(useSessionStore.getState().connectionState).toBe("disconnected");
  });

  it("onGiveUp 置 disconnected", () => {
    useSessionStore.setState({ connectionState: "reconnecting" });
    createConnectionHandlers("s1").onGiveUp();
    expect(useSessionStore.getState().connectionState).toBe("disconnected");
  });

  it("onOpen 首连（reconnected=false）只置 connected、不触发 resync（不覆盖乐观 user 消息）", () => {
    useSessionStore.setState({ connectionState: "reconnecting" });
    const spy = vi.spyOn(api, "getSession").mockResolvedValue({ status: "idle", messages: [] });
    createConnectionHandlers("s1").onOpen({ reconnected: false });
    expect(useSessionStore.getState().connectionState).toBe("connected");
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it("onOpen 重连（reconnected=true）置 connected 并触发非破坏性 resync", async () => {
    useSessionStore.setState({ connectionState: "reconnecting", currentSessionId: "s1", messages: [] });
    const spy = vi.spyOn(api, "getSession").mockResolvedValue({
      status: "done",
      messages: [{ id: "m1", role: "assistant", content: "recovered", timestamp: "t" }],
    });
    createConnectionHandlers("s1").onOpen({ reconnected: true });
    expect(useSessionStore.getState().connectionState).toBe("connected");
    expect(spy).toHaveBeenCalledWith("s1");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(useSessionStore.getState().messages.map((item) => item.id)).toEqual(["m1"]);
    spy.mockRestore();
  });
});
