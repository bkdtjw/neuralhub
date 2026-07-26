import { useState } from "react";
import { ChevronDown, ChevronRight, Trash2 } from "lucide-react";

import type { Session } from "@/types";

interface SessionListProps {
  sessions: Session[];
  currentSessionId: string | null;
  loading?: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}

interface SessionGroup {
  key: string;
  label: string;
  sessions: Session[];
}

const clamp = (text: string, size: number): string => (text.length > size ? `${text.slice(0, size)}...` : text);

const getSessionTitle = (session: Session): string => clamp(session.title.trim() || "新对话", 28);

const DAY_MS = 86_400_000;
const TIME_GROUPS = [
  { key: "today", label: "今天" },
  { key: "yesterday", label: "昨天" },
  { key: "last7", label: "最近 7 天" },
  { key: "older", label: "更早" },
];

const startOfDay = (date: Date): number => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();

const getTimeGroupKey = (iso: string): string => {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "older";
  const diffDays = Math.floor((startOfDay(new Date()) - startOfDay(date)) / DAY_MS);
  if (diffDays <= 0) return "today";
  if (diffDays === 1) return "yesterday";
  if (diffDays < 7) return "last7";
  return "older";
};

const groupSessions = (sessions: Session[]): SessionGroup[] => {
  const sorted = [...sessions].sort((left, right) => new Date(right.createdAt).getTime() - new Date(left.createdAt).getTime());
  const groups = new Map<string, Session[]>(TIME_GROUPS.map((group) => [group.key, []]));
  for (const session of sorted) {
    const key = getTimeGroupKey(session.createdAt);
    const list = groups.get(key) ?? [];
    list.push(session);
    groups.set(key, list);
  }
  return TIME_GROUPS.map((group) => ({ ...group, sessions: groups.get(group.key) ?? [] })).filter((group) => group.sessions.length);
};

function TimeGroup({
  group,
  currentSessionId,
  collapsed,
  onToggle,
  onSelect,
  onDelete,
}: {
  group: SessionGroup;
  currentSessionId: string | null;
  collapsed: boolean;
  onToggle: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const hasActive = group.sessions.some((session) => session.id === currentSessionId);

  return (
    <div className="mb-0.5">
      <button
        type="button"
        onClick={onToggle}
        className={`flex h-7 w-full items-center gap-1.5 rounded-lg px-2 text-left text-xs transition-colors hover:bg-white/[0.05] ${
          hasActive ? "text-[var(--as-text)]" : "text-[var(--as-text-secondary)]"
        }`}
      >
        {collapsed ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
        <span className="min-w-0 flex-1 truncate font-medium">{group.label}</span>
        <span className="rounded-full bg-white/[0.06] px-1.5 py-0.5 text-[10px] leading-none text-[var(--as-text-subtle)] ring-1 ring-white/10">
          {group.sessions.length}
        </span>
      </button>

      {!collapsed ? (
        <div className="mt-1 space-y-0.5">
          {group.sessions.map((session) => {
            const active = session.id === currentSessionId;
            return (
              <div
                key={session.id}
                className={`group relative flex w-full items-center overflow-hidden rounded-xl border transition-colors duration-150 ${
                  active
                    ? "border-white/12 bg-white/[0.08] shadow-[inset_0_1px_0_rgba(255,255,255,0.07)]"
                    : "border-transparent hover:bg-white/[0.05]"
                }`}
              >
                {active ? (
                  <span className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full bg-[var(--as-accent)] shadow-[0_0_8px_var(--as-accent)]" />
                ) : null}
                <button
                  type="button"
                  onClick={() => onSelect(session.id)}
                  className="flex min-w-0 flex-1 items-center gap-2.5 px-3 py-2 text-left"
                >
                  <span
                    className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                      active ? "bg-[var(--as-accent)] shadow-[0_0_7px_var(--as-accent)]" : "bg-white/20"
                    }`}
                  />
                  <div className={`min-w-0 flex-1 truncate text-[13px] ${active ? "text-[var(--as-text-bright)]" : "text-[var(--as-text)]"}`}>
                    {getSessionTitle(session)}
                  </div>
                </button>
                <button
                  type="button"
                  aria-label="删除会话"
                  onClick={(event) => {
                    event.stopPropagation();
                    onDelete(session.id);
                  }}
                  className="mr-1.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg text-[var(--as-text-subtle)] opacity-0 transition-colors hover:bg-white/10 hover:text-rose-300 group-hover:opacity-100"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

export default function SessionList({ sessions, currentSessionId, loading = false, onSelect, onDelete }: SessionListProps) {
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});

  // 首次加载中渲骨架灰条，而不是闪「暂无会话」。
  if (loading && !sessions.length) {
    return (
      <div aria-hidden className="space-y-1.5 px-1 py-2">
        {Array.from({ length: 3 }, (_, index) => (
          <div key={index} className="h-8 animate-pulse rounded-xl bg-white/[0.05]" />
        ))}
      </div>
    );
  }

  if (!sessions.length) {
    return <div className="px-3 py-6 text-xs text-[var(--as-text-subtle)]">暂无会话</div>;
  }

  const groups = groupSessions(sessions);

  return (
    <div className="space-y-0.5">
      {groups.map((group) => (
        <TimeGroup
          key={group.key}
          group={group}
          currentSessionId={currentSessionId}
          collapsed={collapsedGroups[group.key] ?? false}
          onToggle={() => setCollapsedGroups((state) => ({ ...state, [group.key]: !(state[group.key] ?? false) }))}
          onSelect={onSelect}
          onDelete={onDelete}
        />
      ))}
    </div>
  );
}
