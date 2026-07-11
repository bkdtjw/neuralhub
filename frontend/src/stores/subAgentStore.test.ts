import { beforeEach, describe, expect, it } from "vitest";

import { isRunActive, useSubAgentStore } from "./subAgentStore";
import type { SubAgentProgress } from "@/types";

const ingest = (p: SubAgentProgress) => useSubAgentStore.getState().ingest("s1", p);

describe("subAgentStore", () => {
  beforeEach(() => {
    useSubAgentStore.setState({ runs: {}, lastRunId: "" });
  });

  it("聚合一次编排:运行级→阶段→进度→完成", () => {
    ingest({ type: "sub_agent_spawned", runId: "r1", source: "orchestrate", total: 2, specs: ["a", "b"], message: "编排启动" });
    ingest({ type: "sub_agent_spawned", runId: "r1", source: "orchestrate", stage: 0, total: 2, specs: ["a", "b"] });
    ingest({ type: "sub_agent_progress", runId: "r1", source: "orchestrate", stage: 0, role: "a", kind: "tool_call", preview: "Read(x)" });
    ingest({ type: "sub_agent_completed", runId: "r1", source: "orchestrate", stage: 0, role: "a", completed: 1, total: 2 });

    const run = Object.values(useSubAgentStore.getState().runs)[0];
    expect(run.source).toBe("orchestrate");
    expect(run.total).toBe(2);
    expect(run.doneCount).toBe(1);
    expect(run.message).toBe("编排启动");
    expect(run.agents.a.status).toBe("done");
    expect(run.agents.a.activities).toHaveLength(1);
    expect(run.agents.b.status).toBe("running");
    expect(isRunActive(run)).toBe(true);

    ingest({ type: "sub_agent_failed", runId: "r1", source: "orchestrate", stage: 0, role: "b", completed: 2, total: 2, error: "boom" });
    const finished = Object.values(useSubAgentStore.getState().runs)[0];
    expect(finished.agents.b.status).toBe("failed");
    expect(finished.agents.b.error).toBe("boom");
    expect(isRunActive(finished)).toBe(false);
  });

  it("skipped 标记为跳过而非失败", () => {
    ingest({ type: "sub_agent_failed", runId: "r2", source: "orchestrate", stage: 1, role: "c", completed: 3, total: 3, skipped: true });
    const run = Object.values(useSubAgentStore.getState().runs)[0];
    expect(run.agents.c.status).toBe("skipped");
  });

  it("缺 runId 时按来源兜底聚合且按会话隔离", () => {
    ingest({ type: "sub_agent_spawned", source: "dispatch", total: 1, specs: ["helper"] });
    useSubAgentStore.getState().ingest("s2", { type: "sub_agent_spawned", source: "dispatch", total: 1, specs: ["other"] });
    const runs = Object.values(useSubAgentStore.getState().runs);
    expect(runs).toHaveLength(2);
    expect(runs.filter((run) => run.sessionId === "s1")).toHaveLength(1);
    useSubAgentStore.getState().clearSession("s1");
    expect(Object.values(useSubAgentStore.getState().runs)).toHaveLength(1);
  });
});
