import { create } from "zustand";

import type { SubAgentProgress, SubAgentSource } from "@/types";

export type SubAgentStatus = "pending" | "running" | "done" | "failed" | "skipped";

export interface SubAgentActivity {
  kind: string;
  preview: string;
  ts: number;
}

export interface SubAgentEntry {
  role: string;
  stage?: number;
  status: SubAgentStatus;
  activities: SubAgentActivity[];
  error?: string;
  updatedAt: number;
}

export interface SubAgentRun {
  runId: string;
  sessionId: string;
  source: SubAgentSource;
  startedAt: number;
  updatedAt: number;
  total: number;
  doneCount: number;
  message: string;
  agents: Record<string, SubAgentEntry>;
  order: string[];
}

interface SubAgentState {
  runs: Record<string, SubAgentRun>;
  lastRunId: string;
  ingest: (sessionId: string, p: SubAgentProgress) => void;
  clearSession: (sessionId: string) => void;
}

const MAX_ACTIVITIES = 60;

const runKey = (sessionId: string, p: SubAgentProgress): string =>
  `${sessionId}:${p.runId || `${p.source ?? "run"}-live`}`;

const ensureAgent = (run: SubAgentRun, role: string, stage?: number): SubAgentEntry => {
  const existing = run.agents[role];
  if (existing) {
    if (stage !== undefined && existing.stage === undefined) existing.stage = stage;
    return existing;
  }
  const entry: SubAgentEntry = { role, stage, status: "pending", activities: [], updatedAt: Date.now() };
  run.agents[role] = entry;
  run.order.push(role);
  return entry;
};

const applyEvent = (run: SubAgentRun, p: SubAgentProgress): void => {
  const now = Date.now();
  run.updatedAt = now;
  if (p.type === "sub_agent_spawned") {
    if (p.stage === undefined && (p.total ?? 0) >= run.total) run.total = p.total ?? run.total;
    if (p.stage === undefined && p.message) run.message = p.message;
    // 编排的运行级事件只是"预告全员名单"，下游 agent 要等自己的阶段启动才算运行中。
    const startNow = p.stage !== undefined || p.source !== "orchestrate";
    for (const role of p.specs ?? []) {
      const agent = ensureAgent(run, role, p.stage);
      if (agent.status === "pending" && startNow) agent.status = "running";
      agent.updatedAt = now;
    }
    // dispatch/spawn 没有运行级事件，用阶段事件兜底 total
    if (run.total === 0 && p.total) run.total = p.total;
    return;
  }
  if (p.type === "sub_agent_progress") {
    const agent = ensureAgent(run, p.role || "sub-agent", p.stage);
    if (agent.status === "pending") agent.status = "running";
    agent.activities.push({ kind: p.kind || "message", preview: p.preview || "", ts: now });
    if (agent.activities.length > MAX_ACTIVITIES) agent.activities.shift();
    agent.updatedAt = now;
    return;
  }
  const role = p.role || p.specId || "sub-agent";
  const agent = ensureAgent(run, role, p.stage);
  agent.status = p.skipped ? "skipped" : p.type === "sub_agent_failed" ? "failed" : "done";
  agent.error = p.error || undefined;
  agent.updatedAt = now;
  if (p.completed !== undefined) run.doneCount = Math.max(run.doneCount, p.completed);
  if (p.total !== undefined && p.total > run.total) run.total = p.total;
};

export const useSubAgentStore = create<SubAgentState>((set, get) => ({
  runs: {},
  lastRunId: "",
  ingest: (sessionId, p) => {
    const key = runKey(sessionId, p);
    const runs = { ...get().runs };
    const existing = runs[key];
    const run: SubAgentRun = existing
      ? { ...existing, agents: { ...existing.agents }, order: [...existing.order] }
      : {
          runId: key,
          sessionId,
          source: p.source ?? "spawn",
          startedAt: Date.now(),
          updatedAt: Date.now(),
          total: 0,
          doneCount: 0,
          message: "",
          agents: {},
          order: [],
        };
    applyEvent(run, p);
    runs[key] = run;
    set({ runs, lastRunId: key });
  },
  clearSession: (sessionId) => {
    const runs = Object.fromEntries(
      Object.entries(get().runs).filter(([, run]) => run.sessionId !== sessionId),
    );
    set({ runs });
  },
}));

export const isRunActive = (run: SubAgentRun): boolean =>
  Object.values(run.agents).some((agent) => agent.status === "running" || agent.status === "pending");
