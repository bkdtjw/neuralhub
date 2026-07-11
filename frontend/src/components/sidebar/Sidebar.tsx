import { useEffect } from "react";
import { Activity, Database, FileText, FolderOpen, LayoutDashboard, Plus, Radar, Settings, Sparkles, type LucideIcon } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

import SessionList from "@/components/sidebar/SessionList";
import { useAgentStore } from "@/stores/agentStore";
import { useSessionStore } from "@/stores/sessionStore";

export default function Sidebar() {
  const navigate = useNavigate();
  const location = useLocation();
  const sessions = useSessionStore((state) => state.sessions);
  const currentSessionId = useSessionStore((state) => state.currentSessionId);
  const loadSessions = useSessionStore((state) => state.loadSessions);
  const startDraftSession = useSessionStore((state) => state.startDraftSession);
  const selectSession = useSessionStore((state) => state.selectSession);
  const deleteSession = useSessionStore((state) => state.deleteSession);

  const currentModel = useAgentStore((state) => state.currentModel);
  const currentProviderId = useAgentStore((state) => state.currentProviderId);
  const providers = useAgentStore((state) => state.providers);
  const loadProviders = useAgentStore((state) => state.loadProviders);
  const workspace = useAgentStore((state) => state.workspace);
  const workspaceName = workspace?.split(/[/\\]/).pop();
  const visibleSessions = sessions.filter((session) => session.title.trim() || session.messageCount > 0);

  useEffect(() => {
    void loadSessions();
    void loadProviders();
  }, [loadSessions, loadProviders]);

  const handleNewChat = async () => {
    try {
      if (!providers.length || !currentModel || !currentProviderId) {
        navigate("/settings");
        return;
      }
      startDraftSession();
      navigate("/");
    } catch (error) {
      console.error("create session failed", error);
    }
  };

  const navItems = [
    { path: "/", label: "总览", icon: LayoutDashboard },
    { path: "/hooks", label: "钩子", icon: Radar },
    { path: "/metrics", label: "指标", icon: Activity },
    { path: "/logs", label: "日志", icon: FileText },
    { path: "/knowledge", label: "知识库", icon: Database },
  ];

  return (
    <aside className="flex h-screen w-[220px] min-w-[220px] max-w-[220px] shrink-0 flex-col border-r border-white/10 bg-[var(--as-sidebar)] backdrop-blur-2xl">
      <div className="px-2.5 pb-2 pt-3">
        <div className="mb-3 flex items-center gap-2 px-1.5">
          <div className="flex h-[22px] w-[22px] items-center justify-center rounded-md bg-[linear-gradient(135deg,#3b82f6,#8b5cf6)] shadow-[0_8px_18px_rgb(59_130_246_/_18%)]">
            <Sparkles size={13} strokeWidth={2.2} className="text-white" />
          </div>
          <div className="truncate text-[13px] font-medium text-[var(--as-text-bright)]">NeuralHub</div>
        </div>

        <button type="button" onClick={handleNewChat} className="as-primary-btn h-8 w-full gap-1.5 text-[13px]">
          <Plus size={15} strokeWidth={2.2} />
          <span>{providers.length ? "新建对话" : "配置 Provider"}</span>
        </button>

        <button
          type="button"
          onClick={() => void useAgentStore.getState().openFolder()}
          className="mt-2 flex w-full items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-2 text-left text-xs text-[var(--as-text-secondary)] transition-colors hover:border-white/20 hover:bg-white/[0.07] hover:text-[var(--as-text)]"
        >
          <FolderOpen size={15} className="shrink-0 text-[var(--as-text-muted)]" />
          <span className="min-w-0 truncate">{workspaceName ?? "选择项目文件夹"}</span>
        </button>
        {workspace ? <div className="mt-1 truncate px-1.5 font-mono text-[10px] text-[var(--as-text-subtle)]">{workspace}</div> : null}

        <nav className="mt-3 space-y-px">
          {navItems.map((item) => (
            <NavItem
              key={item.path}
              active={location.pathname === item.path}
              icon={item.icon}
              label={item.label}
              onClick={() => navigate(item.path)}
            />
          ))}
        </nav>
      </div>

      <div className="mx-2 border-t border-[var(--as-border)]" />

      <div className="px-4 pt-3 text-[11px] font-medium uppercase tracking-[0.08em] text-[var(--as-text-subtle)]">会话</div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2 pt-1.5">
        <SessionList
          sessions={visibleSessions}
          currentSessionId={currentSessionId}
          onSelect={(id) => {
            selectSession(id);
            navigate(`/session/${id}`);
          }}
          onDelete={(id) => {
            void deleteSession(id);
            if (id === currentSessionId) navigate("/");
          }}
        />
      </div>

      <div className="border-t border-[var(--as-border)] px-2 py-2.5">
        <NavItem
          active={location.pathname === "/settings"}
          icon={Settings}
          label="设置"
          onClick={() => navigate("/settings")}
        />
      </div>
    </aside>
  );
}

function NavItem({
  active,
  icon: Icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: LucideIcon;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-current={active ? "page" : undefined}
      onClick={onClick}
      className={`relative flex h-[34px] w-full items-center gap-2.5 rounded-[10px] px-3 text-left text-[13px] transition-colors duration-150 ${
        active
          ? "border border-white/10 bg-white/[0.08] text-[var(--as-text-bright)] shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]"
          : "border border-transparent text-[var(--as-text-secondary)] hover:bg-white/[0.05] hover:text-[var(--as-text)]"
      }`}
    >
      {active ? (
        <span className="absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-full bg-[var(--as-accent)] shadow-[0_0_8px_var(--as-accent)]" />
      ) : null}
      <Icon size={16} strokeWidth={2} className={`shrink-0 ${active ? "text-[var(--as-accent)]" : ""}`} />
      <span className="truncate">{label}</span>
    </button>
  );
}
