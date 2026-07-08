import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api-client";
import { agentWs } from "@/lib/websocket";
import { useAgentStore } from "@/stores/agentStore";
import { errorText, useSessionStore } from "@/stores/sessionStore";
import type { Message, Provider, Session, ToolCall } from "@/types";

const call = (id: string, name = "mcp__demo__do"): ToolCall => ({ id, name, arguments: {} });
const ids = (): string[] => useSessionStore.getState().pendingApprovals.map((item) => item.id);

describe("sessionStore pendingApprovals（F2：待审批工具增减）", () => {
  beforeEach(() => {
    useSessionStore.setState({ pendingApprovals: [] });
  });

  it("addPendingApprovals 写入并按 id 去重（重复批次不叠加）", () => {
    useSessionStore.getState().addPendingApprovals([call("a"), call("b")]);
    useSessionStore.getState().addPendingApprovals([call("b"), call("c")]);
    expect(ids()).toEqual(["a", "b", "c"]);
  });

  it("addPendingApprovals 丢弃缺 id 的项（无 tool_call_id 无法回传决策）", () => {
    useSessionStore.getState().addPendingApprovals([call(""), call("a")]);
    expect(ids()).toEqual(["a"]);
  });

  it("removePendingApproval 按 id 精确移除，其余保留", () => {
    useSessionStore.getState().addPendingApprovals([call("a"), call("b")]);
    useSessionStore.getState().removePendingApproval("a");
    expect(ids()).toEqual(["b"]);
  });

  it("removePendingApproval 命中不存在的 id 时保持引用稳定（避免无谓渲染）", () => {
    useSessionStore.getState().addPendingApprovals([call("a")]);
    const before = useSessionStore.getState().pendingApprovals;
    useSessionStore.getState().removePendingApproval("zzz");
    expect(useSessionStore.getState().pendingApprovals).toBe(before);
  });

  it("clearPendingApprovals 清空", () => {
    useSessionStore.getState().addPendingApprovals([call("a"), call("b")]);
    useSessionStore.getState().clearPendingApprovals();
    expect(ids()).toEqual([]);
  });

  it("respondToApproval 在 ws 未连接时保留待审批项（等待重连重试，不静默丢弃）", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    useSessionStore.getState().addPendingApprovals([call("a")]);
    useSessionStore.getState().respondToApproval("a", true);
    expect(ids()).toEqual(["a"]);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});

const provider: Provider = {
  id: "p1",
  name: "Demo",
  providerType: "openai",
  baseUrl: "https://example.com",
  apiKeyPreview: "sk-demo",
  defaultModel: "demo-model",
  availableModels: ["demo-model"],
  isDefault: true,
  enabled: true,
};

const session: Session = {
  id: "s1",
  model: "demo-model",
  status: "idle",
  createdAt: new Date().toISOString(),
  messageCount: 0,
  title: "已有标题",
  workspace: "",
};

describe("sessionStore lastError（F3：后端错误呈现给用户）", () => {
  beforeEach(() => {
    useSessionStore.setState({ lastError: "", status: "idle", messages: [] });
  });

  it("errorText 从 error 事件的 {message} 提取文本（后端异常 / Agent is busy）", () => {
    expect(errorText({ type: "error", message: "Agent is busy" })).toBe("Agent is busy");
    expect(errorText({ message: "LLM 调用失败: boom" })).toBe("LLM 调用失败: boom");
  });

  it("errorText 对原生 Event（socket.onerror 无 message）回退为“连接错误”", () => {
    expect(errorText(new Event("error"))).toBe("连接错误");
  });

  it("errorText 对 undefined / null / 空串 / 非字符串负载回退为“连接错误”（不把 undefined 当错误文本）", () => {
    expect(errorText(undefined)).toBe("连接错误");
    expect(errorText(null)).toBe("连接错误");
    expect(errorText({ message: "" })).toBe("连接错误");
    expect(errorText({ message: 42 })).toBe("连接错误");
  });

  it("setLastError 把归一化后的文本落地到 store（onError 的落地路径）", () => {
    useSessionStore.getState().setLastError(errorText({ message: "boom" }));
    expect(useSessionStore.getState().lastError).toBe("boom");
    useSessionStore.getState().setLastError(errorText(new Event("error")));
    expect(useSessionStore.getState().lastError).toBe("连接错误");
  });

  it("sendMessage 开头把 status 置 thinking 的同一次 set 里清空 lastError", async () => {
    const connectSpy = vi.spyOn(agentWs, "connect").mockResolvedValue(undefined);
    const sendSpy = vi.spyOn(agentWs, "send").mockReturnValue(true);
    useAgentStore.setState({
      currentModel: "demo-model",
      currentProviderId: "p1",
      providers: [provider],
      workspace: "",
      permissionMode: "auto",
      thinkingLevel: "medium",
    });
    useSessionStore.setState({
      currentSessionId: "s1",
      sessions: [session],
      messages: [],
      lastError: "上一次的后端错误",
      status: "error",
    });
    await useSessionStore.getState().sendMessage("你好");
    expect(useSessionStore.getState().lastError).toBe("");
    expect(useSessionStore.getState().status).toBe("thinking");
    connectSpy.mockRestore();
    sendSpy.mockRestore();
  });
});

describe("sessionStore resync（F4：断线重连后非破坏性补偿）", () => {
  beforeEach(() => {
    useSessionStore.setState({ messages: [], status: "idle", currentSessionId: "s1", connectionState: "connected" });
  });

  it("resync 成功时用后端返回替换 messages/status（找回断线期间丢失的助手回复）", async () => {
    const spy = vi.spyOn(api, "getSession").mockResolvedValue({
      status: "done",
      messages: [
        { id: "m1", role: "user", content: "hi", timestamp: "t1" },
        { id: "m2", role: "assistant", content: "hello", timestamp: "t2" },
      ],
    });
    useSessionStore.setState({ messages: [{ id: "old", role: "user", content: "hi", timestamp: "t0" }], status: "thinking" });
    await useSessionStore.getState().resync("s1");
    expect(useSessionStore.getState().messages.map((item) => item.id)).toEqual(["m1", "m2"]);
    expect(useSessionStore.getState().status).toBe("done");
    spy.mockRestore();
  });

  it("resync 失败（后端 5xx / 断连）时保留旧 messages 与 status（绝不清空）", async () => {
    const old: Message[] = [{ id: "old", role: "user", content: "hi", timestamp: "t0" }];
    useSessionStore.setState({ messages: old, status: "thinking" });
    const spy = vi.spyOn(api, "getSession").mockRejectedValue(new Error("backend down"));
    const err = vi.spyOn(console, "error").mockImplementation(() => undefined);
    await useSessionStore.getState().resync("s1");
    expect(useSessionStore.getState().messages).toBe(old);
    expect(useSessionStore.getState().status).toBe("thinking");
    spy.mockRestore();
    err.mockRestore();
  });

  it("resync 成功但返回空 messages 时保留旧 messages（后端未持久化 / 竞态，绝不清空）", async () => {
    const old: Message[] = [{ id: "old", role: "user", content: "hi", timestamp: "t0" }];
    useSessionStore.setState({ messages: old });
    const spy = vi.spyOn(api, "getSession").mockResolvedValue({ status: "done", messages: [] });
    await useSessionStore.getState().resync("s1");
    expect(useSessionStore.getState().messages).toBe(old);
    spy.mockRestore();
  });

  it("resync 目标会话与当前会话不一致时直接放弃（不污染已切换到的会话）", async () => {
    const old: Message[] = [{ id: "old", role: "user", content: "hi", timestamp: "t0" }];
    useSessionStore.setState({ messages: old, currentSessionId: "s2" });
    const spy = vi.spyOn(api, "getSession").mockResolvedValue({
      status: "done",
      messages: [{ id: "x", role: "user", content: "x", timestamp: "t" }],
    });
    await useSessionStore.getState().resync("s1");
    expect(useSessionStore.getState().messages).toBe(old);
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});

describe("sessionStore connectionState（F4：连接状态指示）", () => {
  beforeEach(() => {
    useSessionStore.setState({ connectionState: "connected" });
  });

  it("setConnectionState 落地 open/close/give-up 事件对应的连接状态", () => {
    useSessionStore.getState().setConnectionState("reconnecting");
    expect(useSessionStore.getState().connectionState).toBe("reconnecting");
    useSessionStore.getState().setConnectionState("disconnected");
    expect(useSessionStore.getState().connectionState).toBe("disconnected");
    useSessionStore.getState().setConnectionState("connected");
    expect(useSessionStore.getState().connectionState).toBe("connected");
  });
});
