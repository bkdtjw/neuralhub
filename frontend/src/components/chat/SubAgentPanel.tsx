import { useMemo, useState } from "react";
import { Bot, ChevronDown, ChevronRight, Hammer, MessageSquare, Undo2, X } from "lucide-react";

import { isRunActive, useSubAgentStore } from "@/stores/subAgentStore";
import type { SubAgentEntry, SubAgentRun, SubAgentStatus } from "@/stores/subAgentStore";

const SOURCE_LABEL: Record<string, string> = {
  orchestrate: "DAG 编排",
  dispatch: "定向派发",
  spawn: "队列并行",
};

const STATUS_META: Record<SubAgentStatus, { label: string; dot: string }> = {
  pending: { label: "等待", dot: "bg-[var(--as-text-subtle)]" },
  running: { label: "运行中", dot: "animate-pulse bg-[var(--as-thinking)]" },
  done: { label: "完成", dot: "bg-[var(--as-success)]" },
  failed: { label: "失败", dot: "bg-[var(--as-danger)]" },
  skipped: { label: "跳过", dot: "bg-[var(--as-text-subtle)]" },
};

const KIND_ICON: Record<string, typeof Hammer> = {
  tool_call: Hammer,
  tool_result: Undo2,
  message: MessageSquare,
};

export default function SubAgentPanel({ sessionId, onClose }: { sessionId: string; onClose: () => void }) {
  const runsMap = useSubAgentStore((state) => state.runs);
  const runs = useMemo(
    () =>
      Object.values(runsMap)
        .filter((run) => run.sessionId === sessionId)
        .sort((a, b) => b.startedAt - a.startedAt),
    [runsMap, sessionId],
  );

  return (
    <aside className="flex w-[320px] shrink-0 flex-col border-l border-[var(--as-border)] bg-[var(--as-surface-low)]">
      <div className="flex h-10 shrink-0 items-center justify-between border-b border-[var(--as-border)] px-3">
        <div className="flex items-center gap-1.5 text-[12px] font-medium text-[var(--as-text)]">
          <Bot size={14} className="text-[var(--as-accent)]" />
          子 Agent 面板
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-1 text-[var(--as-text-subtle)] transition hover:bg-[var(--as-hover)] hover:text-[var(--as-text)]"
          aria-label="关闭子 Agent 面板"
        >
          <X size={14} />
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {runs.length === 0 ? (
          <p className="px-1 pt-2 text-[12px] leading-5 text-[var(--as-text-subtle)]">
            本会话还没有子 agent 活动。当主 agent 编排（orchestrate_agents）、派发（dispatch_agent）
            或队列并行（spawn_agent）子 agent 时，这里会实时显示每个子 agent 的运行过程。
          </p>
        ) : (
          runs.map((run) => <RunCard key={run.runId} run={run} />)
        )}
      </div>
    </aside>
  );
}

function RunCard({ run }: { run: SubAgentRun }) {
  const active = isRunActive(run);
  const stageGroups = useMemo(() => {
    const groups = new Map<number | undefined, SubAgentEntry[]>();
    for (const role of run.order) {
      const agent = run.agents[role];
      const list = groups.get(agent.stage) ?? [];
      list.push(agent);
      groups.set(agent.stage, list);
    }
    return [...groups.entries()].sort((a, b) => (a[0] ?? -1) - (b[0] ?? -1));
  }, [run]);
  const total = run.total || run.order.length;

  return (
    <section className="rounded-[11px] border border-[var(--as-border)] bg-[var(--as-surface)] shadow-[var(--as-shadow)]">
      <header className="flex items-center gap-2 border-b border-[var(--as-border)] px-3 py-2">
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${active ? "animate-pulse bg-[var(--as-thinking)]" : "bg-[var(--as-success)]"}`} />
        <span className="rounded border border-[var(--as-border-strong)] bg-[var(--as-surface-low)] px-1.5 py-0.5 text-[10px] text-[var(--as-text-secondary)]">
          {SOURCE_LABEL[run.source] ?? run.source}
        </span>
        <span className="ml-auto font-mono text-[11px] text-[var(--as-text-secondary)]">
          {run.doneCount}/{total}
        </span>
      </header>
      {run.message ? (
        <p className="border-b border-[var(--as-border)] px-3 py-1.5 text-[11px] leading-4 text-[var(--as-text-subtle)]">{run.message}</p>
      ) : null}
      <div className="px-2 py-1.5">
        {stageGroups.map(([stage, agents]) => (
          <div key={stage ?? "flat"}>
            {run.source === "orchestrate" && stage !== undefined ? (
              <div className="px-1 pb-0.5 pt-1.5 text-[10px] font-medium uppercase tracking-wide text-[var(--as-text-subtle)]">
                阶段 {stage}
              </div>
            ) : null}
            {agents.map((agent) => (
              <AgentRow key={agent.role} agent={agent} />
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

function AgentRow({ agent }: { agent: SubAgentEntry }) {
  const [expanded, setExpanded] = useState(false);
  const meta = STATUS_META[agent.status];
  const expandable = agent.activities.length > 0 || Boolean(agent.error);

  return (
    <div className="rounded-md">
      <button
        type="button"
        onClick={() => expandable && setExpanded((value) => !value)}
        className={`flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left transition ${expandable ? "hover:bg-[var(--as-hover)]" : "cursor-default"}`}
      >
        <span className={`h-2 w-2 shrink-0 rounded-full ${meta.dot}`} />
        <span className="truncate text-[12px] text-[var(--as-text)]">{agent.role}</span>
        <span className="ml-auto shrink-0 text-[10px] text-[var(--as-text-subtle)]">{meta.label}</span>
        {expandable ? (
          expanded ? (
            <ChevronDown size={12} className="shrink-0 text-[var(--as-text-subtle)]" />
          ) : (
            <ChevronRight size={12} className="shrink-0 text-[var(--as-text-subtle)]" />
          )
        ) : null}
      </button>
      {expanded ? (
        <div className="mb-1 ml-3 space-y-1 border-l border-[var(--as-border)] pl-2.5">
          {agent.activities.map((activity, index) => {
            const Icon = KIND_ICON[activity.kind] ?? MessageSquare;
            return (
              <div key={index} className="flex items-start gap-1.5 text-[11px] leading-4 text-[var(--as-text-secondary)]">
                <Icon size={11} className="mt-0.5 shrink-0 text-[var(--as-text-subtle)]" />
                <span className="break-all">{activity.preview}</span>
              </div>
            );
          })}
          {agent.error ? (
            <div className="text-[11px] leading-4 text-[var(--as-danger)]">{agent.error}</div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
