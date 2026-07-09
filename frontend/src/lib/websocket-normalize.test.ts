import { describe, expect, it } from "vitest";

import { normalizeWsIncoming } from "@/lib/websocket-normalize";

describe("normalizeWsIncoming", () => {
  describe("兜底中性化（F1：未知事件不再误判为 error）", () => {
    // 合并 event-hooks 后 sub_agent_spawned/completed/failed 已是一等事件（见下方 describe），
    // 不再走 ignored 兜底；F1 意图（真正未知事件 → ignored 而非 error）改用未接线的事件类型验证。
    it("未知事件归一化为 ignored 而非 error", () => {
      const result = normalizeWsIncoming({ type: "plan_resume_available", agent_id: "a1" });
      expect(result.type).toBe("ignored");
    });

    it("后端其余未知事件均归一化为 ignored，不打成 error", () => {
      // 注：tool_approval_required 自 F2 起有显式分支、sub_agent_* 自 event-hooks 起有显式分支，均不再 ignored。
      const types = ["plan_resume_available", "presence_update", "some_future_event"];
      for (const type of types) {
        expect(normalizeWsIncoming({ type }).type).toBe("ignored");
      }
    });

    it("ignored 透传原始 raw 以便调试", () => {
      const raw = { type: "plan_resume_available", agent_id: "a1" };
      expect(normalizeWsIncoming(raw)).toEqual({ type: "ignored", raw });
    });

    it("缺失 type 的载荷也归一化为 ignored（不再默认 error）", () => {
      expect(normalizeWsIncoming({ message: "no type here" }).type).toBe("ignored");
    });
  });

  describe("sub_agent_* 事件（event-hooks：一等事件，不再 ignored）", () => {
    it("sub_agent_spawned/completed/failed 被识别并透传类型", () => {
      for (const type of ["sub_agent_spawned", "sub_agent_completed", "sub_agent_failed"]) {
        expect(normalizeWsIncoming({ type }).type).toBe(type);
      }
    });

    it("sub_agent_completed 解析进度字段（snake_case→camelCase）", () => {
      const result = normalizeWsIncoming({
        type: "sub_agent_completed",
        task_id: "t1",
        spec_id: "s1",
        completed: 2,
        total: 3,
      });
      expect(result).toMatchObject({
        type: "sub_agent_completed",
        taskId: "t1",
        specId: "s1",
        completed: 2,
        total: 3,
      });
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
