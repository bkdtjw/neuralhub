import { describe, expect, it } from "vitest";

import { normalizeWsIncoming } from "@/lib/websocket-normalize";

describe("normalizeWsIncoming", () => {
  describe("兜底中性化（F1：未知事件不再误判为 error）", () => {
    it("未知事件 sub_agent_spawned 归一化为 ignored 而非 error", () => {
      const result = normalizeWsIncoming({ type: "sub_agent_spawned", agent_id: "a1" });
      expect(result.type).toBe("ignored");
    });

    it("后端其余正常事件均归一化为 ignored，不打成 error", () => {
      // 注：tool_approval_required 自 F2 起有显式分支（见下方 describe），不再归为 ignored。
      const types = ["sub_agent_completed", "sub_agent_failed", "plan_resume_available"];
      for (const type of types) {
        expect(normalizeWsIncoming({ type }).type).toBe("ignored");
      }
    });

    it("ignored 透传原始 raw 以便调试", () => {
      const raw = { type: "sub_agent_spawned", agent_id: "a1" };
      expect(normalizeWsIncoming(raw)).toEqual({ type: "ignored", raw });
    });

    it("缺失 type 的载荷也归一化为 ignored（不再默认 error）", () => {
      expect(normalizeWsIncoming({ message: "no type here" }).type).toBe("ignored");
    });
  });

  describe("真实 error 分支语义保持不变（终止态）", () => {
    it("显式 error 仍返回 error 且 message 透传", () => {
      expect(normalizeWsIncoming({ type: "error", message: "boom" })).toEqual({
        type: "error",
        message: "boom",
      });
    });

    it("error 缺失 message 时使用默认文案", () => {
      expect(normalizeWsIncoming({ type: "error" })).toEqual({
        type: "error",
        message: "Unknown websocket error",
      });
    });
  });

  describe("既有分支不回归", () => {
    it("status 透传", () => {
      expect(normalizeWsIncoming({ type: "status", status: "thinking" })).toEqual({
        type: "status",
        status: "thinking",
      });
    });

    it("status 缺省回落 error 状态", () => {
      expect(normalizeWsIncoming({ type: "status" })).toEqual({ type: "status", status: "error" });
    });

    it("message 携带 tool_calls 与 reasoning_content", () => {
      const toolCalls = [{ id: "t1", name: "read", arguments: { path: "a" } }];
      expect(
        normalizeWsIncoming({
          type: "message",
          content: "hi",
          reasoning_content: "because",
          tool_calls: toolCalls,
        }),
      ).toEqual({ type: "message", content: "hi", reasoningContent: "because", toolCalls });
    });

    it("tool_call 透传 id/name/arguments", () => {
      expect(
        normalizeWsIncoming({ type: "tool_call", id: "t1", name: "bash", arguments: { cmd: "ls" } }),
      ).toEqual({ type: "tool_call", id: "t1", name: "bash", arguments: { cmd: "ls" } });
    });

    it("tool_result 映射 snake_case 字段并补空 diffs", () => {
      expect(
        normalizeWsIncoming({ type: "tool_result", tool_call_id: "t1", output: "ok", is_error: false }),
      ).toEqual({ type: "tool_result", toolCallId: "t1", output: "ok", isError: false, diffs: [] });
    });
  });

  describe("tool_approval_required（F2：解析待审批工具）", () => {
    it("解析 tool_calls（映射 id/name/arguments）与 timeout_seconds", () => {
      const result = normalizeWsIncoming({
        type: "tool_approval_required",
        tool_calls: [
          { id: "c1", name: "mcp__demo__do", arguments: { a: 1 } },
          { id: "c2", name: "bash", arguments: { command: "ls" } },
        ],
        timeout_seconds: 300,
      });
      expect(result).toEqual({
        type: "tool_approval_required",
        toolCalls: [
          { id: "c1", name: "mcp__demo__do", arguments: { a: 1 } },
          { id: "c2", name: "bash", arguments: { command: "ls" } },
        ],
        timeoutSeconds: 300,
      });
    });

    it("单个 call 缺字段时安全兜底：缺 id/name 回落空串、缺 arguments 回落空对象", () => {
      expect(
        normalizeWsIncoming({ type: "tool_approval_required", tool_calls: [{ name: "do" }] }),
      ).toEqual({
        type: "tool_approval_required",
        toolCalls: [{ id: "", name: "do", arguments: {} }],
      });
    });

    it("缺 tool_calls / timeout_seconds 时返回空列表且不带 timeoutSeconds", () => {
      expect(normalizeWsIncoming({ type: "tool_approval_required" })).toEqual({
        type: "tool_approval_required",
        toolCalls: [],
      });
    });

    it("timeout_seconds 非法（0 或 NaN）时省略该字段", () => {
      expect(normalizeWsIncoming({ type: "tool_approval_required", timeout_seconds: 0 })).toEqual({
        type: "tool_approval_required",
        toolCalls: [],
      });
      expect(
        normalizeWsIncoming({ type: "tool_approval_required", timeout_seconds: "oops" }),
      ).toEqual({ type: "tool_approval_required", toolCalls: [] });
    });
  });
});
