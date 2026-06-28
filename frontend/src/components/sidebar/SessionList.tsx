import { useState } from "react";
import { ChevronDown, ChevronRight, MessageSquare, Trash2 } from "lucide-react";

import type { Session } from "@/types";

interface SessionListProps {
  sessions: Session[];
  currentSessionId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}

interface SessionGroup {
  key: string;
  label: string;
  sessions: Session[];
}

const clamp = (text: string, size: number): string => (text.length > size ? `${text.slice(0, size)}...` : text);

const formatRelativeTime = (iso: string): string => {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const diffMinutes = Math.floor((Date.now() - date.getTime()) / 60000);
  if (diffMinutes < 1) return "刚刚";
  if (diffMinutes < 60) return `${diffMinutes} 分钟前`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours} 小时前`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays} 天前`;
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
};

const formatModel = (model: string): string => {
  const clean = model.split("/").pop() ?? model;
  return clean || "默认模型";
};

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
        <div className="ml-2.5 border-l border-white/10 pl-1.5">
          {group.sessions.map((session) => {
            const active = session.id === currentSessionId;
            return (
              <div
                key={session.id}
                className={`group relative flex w-full items-center rounded-lg border transition-colors ${
                  active
                    ? "border-white/10 bg-white/[0.07] text-[var(--as-text)] shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]"
                    : "border-transparent text-[var(--as-text-secondary)] hover:bg-white/[0.05] hover:text-[var(--as-text)]"
                }`}
              >
                {active ? (
                  <span className="absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-full bg-[var(--as-accent)] shadow-[0_0_8px_var(--as-accent)]" />
                ) : null}
                <button
                  type="button"
                  onClick={() => onSelect(session.id)}
                  className="flex min-w-0 flex-1 items-start gap-1.5 rounded-md px-2 py-1.5 text-left"
                >
                  <MessageSquare size={13} className="mt-0.5 shrink-0 text-[var(--as-text-subtle)]" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] leading-[17px]">{getSessionTitle(session)}</div>
                    <div className="flex min-w-0 items-center gap-1.5 truncate font-mono text-[10px] leading-3 text-[var(--as-text-subtle)]">
                      <span>{formatRelativeTime(session.createdAt)}</span>
                      <span className="hidden min-w-0 truncate group-hover:inline">{formatModel(session.model)}</span>
                    </div>
                  </div>
                </button>
                <button
                  type="button"
                  aria-label="删除会话"
                  onClick={(event) => {
                    event.stopPropagation();
                    onDelete(session.id);
                  }}
                  className="mr-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[var(--as-text-subtle)] opacity-0 hover:bg-[var(--as-surface)] hover:text-[var(--as-text)] group-hover:opacity-100"
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

export default function SessionList({ sessions, currentSessionId, onSelect, onDelete }: SessionListProps) {
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});

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
