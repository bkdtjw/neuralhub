import { useEffect, useState } from "react";
import { Server } from "lucide-react";
import EmptyState from "@/components/common/EmptyState";
import TokenUsagePanel from "@/components/settings/TokenUsagePanel";
import ProviderModal from "@/components/settings/ProviderModal";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { api } from "@/lib/api-client";
import { useAgentStore } from "@/stores/agentStore";
import type { Provider } from "@/types";

type SettingsSection = "providers" | "tokens";
const SECTIONS: { id: SettingsSection; label: string }[] = [{ id: "providers", label: "Providers" }, { id: "tokens", label: "Token 消耗" }];
const typeLabel: Record<string, string> = {
  openai_compat: "OpenAI Compatible",
  anthropic: "Anthropic",
  ollama: "Ollama",
  claude_code: "Claude Code",
};
export default function Settings() {
  useDocumentTitle("设置");
  const [section, setSection] = useState<SettingsSection>("providers");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Provider | null>(null);
  // per-id in-flight 保护：设为默认/删除进行中禁用该卡片操作，失败在卡片内红字反馈。
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [cardErrors, setCardErrors] = useState<Record<string, string>>({});
  const refreshAgentProviders = useAgentStore((state) => state.loadProviders);
  const loadProviders = async () => {
    try {
      setLoading(true);
      setError("");
      const data = await api.listProviders();
      setProviders(data);
      await refreshAgentProviders();
    } catch (err) {
      setError((err as Error).message || "加载失败");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void loadProviders();
  }, []);
  const runProviderAction = async (id: string, action: () => Promise<unknown>, failText: string) => {
    if (pendingId) return;
    setPendingId(id);
    setCardErrors((prev) => ({ ...prev, [id]: "" }));
    try {
      await action();
      await loadProviders();
    } catch (err) {
      setCardErrors((prev) => ({ ...prev, [id]: `${failText}: ${(err as Error).message}` }));
    } finally {
      setPendingId(null);
    }
  };
  const openAdd = () => {
    setEditing(null);
    setModalOpen(true);
  };
  const openEdit = (provider: Provider) => {
    setEditing(provider);
    setModalOpen(true);
  };
  return (
    <div className="flex h-full min-h-0 bg-[var(--as-bg)] text-[var(--as-text)]">
      <aside className="w-56 shrink-0 border-r border-[var(--as-border)] bg-[var(--as-sidebar)] p-3">
        <div className="space-y-1">
          {SECTIONS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setSection(item.id)}
              className={`block w-full rounded-md px-3 py-2 text-left text-sm ${
                section === item.id
                  ? "border-l-[2.5px] border-[var(--as-accent)] bg-[var(--as-surface)]"
                  : "text-[var(--as-text-secondary)] hover:bg-[var(--as-hover)]"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </aside>
      <section className="min-w-0 flex-1 overflow-y-auto p-6">
        {section === "tokens" ? (
          <div>
            <h2 className="mb-5 text-2xl font-medium">Token 消耗</h2>
            <TokenUsagePanel />
          </div>
        ) : (
          <div>
            <div className="mb-5 flex items-center justify-between">
              <h2 className="text-2xl font-medium">LLM Providers</h2>
              <button type="button" onClick={openAdd} className="as-primary-btn px-4 py-2 text-sm">添加</button>
            </div>
            {loading ? <div className="text-sm text-[var(--as-text-secondary)]">加载中...</div> : null}
            {error ? <div className="mb-3 rounded border border-red-500/50 bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</div> : null}
            {!loading && !error && !providers.length ? (
              <div className="flex justify-center py-14">
                <div className="w-full max-w-[420px]">
                  <EmptyState
                    icon={Server}
                    title="还没有配置 Provider"
                    description="添加一个 LLM Provider，NeuralHub 才能连接模型开始对话"
                    action={{ label: "添加第一个 Provider", onClick: openAdd }}
                  />
                </div>
              </div>
            ) : null}
            <div className="space-y-3">
              {providers.map((provider) => {
                const status = provider.isDefault ? { dot: "bg-emerald-500", text: "默认" } : provider.enabled ? { dot: "bg-[var(--as-text-muted)]", text: "启用" } : { dot: "bg-red-500", text: "禁用" };
                const pending = pendingId === provider.id;
                return (
                  <div key={provider.id} className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="text-base font-medium">{provider.name}</h3>
                          <span className="rounded-md border border-[var(--as-border-strong)] bg-[var(--as-hover)] px-2 py-0.5 text-xs text-[var(--as-text-secondary)]">{typeLabel[provider.providerType] ?? provider.providerType}</span>
                        </div>
                        <div className="mt-1 font-mono text-xs text-[var(--as-text-secondary)]">{provider.baseUrl}</div>
                        <div className="mt-1 text-xs text-[var(--as-text-muted)]">API Key: {provider.apiKeyPreview || "***"}</div>
                        <div className="mt-1 font-mono text-xs text-[var(--as-text-muted)]">默认模型: {provider.defaultModel}</div>
                      </div>
                      <div className="flex items-center gap-2 text-xs text-[var(--as-text-secondary)]"><span className={`h-2.5 w-2.5 rounded-full ${status.dot}`} />{status.text}</div>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      <button type="button" onClick={() => void api.testProvider(provider.id).then((r) => alert(r.ok ? `连接成功 (${r.latency_ms}ms)` : `连接失败: ${r.message}`)).catch((e) => alert(`连接失败: ${String((e as Error).message)}`))} className="rounded-md border border-[var(--as-border-strong)] px-3 py-1.5 text-xs hover:bg-[var(--as-hover)]">测试连接</button>
                      <button type="button" onClick={() => openEdit(provider)} className="rounded-md border border-[var(--as-border-strong)] px-3 py-1.5 text-xs hover:bg-[var(--as-hover)]">编辑</button>
                      <button type="button" disabled={pending} onClick={() => void runProviderAction(provider.id, () => api.setDefault(provider.id), "设为默认失败")} className="rounded-md border border-[var(--as-border-strong)] px-3 py-1.5 text-xs hover:bg-[var(--as-hover)] disabled:cursor-not-allowed disabled:opacity-50">设为默认</button>
                      <button type="button" disabled={pending} onClick={() => { if (window.confirm(`确认删除 ${provider.name} ?`)) void runProviderAction(provider.id, () => api.deleteProvider(provider.id), "删除失败"); }} className="rounded border border-red-500/60 px-3 py-1.5 text-xs text-red-300 hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-50">删除</button>
                    </div>
                    {cardErrors[provider.id] ? <div className="mt-2 text-xs text-[var(--as-danger)]">{cardErrors[provider.id]}</div> : null}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </section>
      <ProviderModal isOpen={modalOpen} editing={editing} onClose={() => setModalOpen(false)} onSaved={loadProviders} />
    </div>
  );
}
