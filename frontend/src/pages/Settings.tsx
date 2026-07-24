import { useEffect, useState } from "react";
import TokenUsagePanel from "@/components/settings/TokenUsagePanel";
import ProviderModal from "@/components/settings/ProviderModal";
import { api } from "@/lib/api-client";
import { useAgentStore } from "@/stores/agentStore";
import type { Provider } from "@/types";

type SettingsSection = "providers" | "tokens";
const SECTIONS: { id: SettingsSection; label: string }[] = [{ id: "providers", label: "Providers" }, { id: "tokens", label: "Token 消耗" }];
const typeLabel: Record<string, string> = {
  openai_compat: "OpenAI Compatible",
  anthropic: "Anthropic",
  ollama: "Ollama",
};
export default function Settings() {
  const [section, setSection] = useState<SettingsSection>("providers");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Provider | null>(null);
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
            <div className="space-y-3">
              {providers.map((provider) => {
                const status = provider.isDefault ? { dot: "bg-emerald-500", text: "默认" } : provider.enabled ? { dot: "bg-[var(--as-text-muted)]", text: "启用" } : { dot: "bg-red-500", text: "禁用" };
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
                      <button type="button" onClick={() => void api.setDefault(provider.id).then(loadProviders)} className="rounded-md border border-[var(--as-border-strong)] px-3 py-1.5 text-xs hover:bg-[var(--as-hover)]">设为默认</button>
                      <button type="button" onClick={() => void (window.confirm(`确认删除 ${provider.name} ?`) && api.deleteProvider(provider.id).then(loadProviders))} className="rounded border border-red-500/60 px-3 py-1.5 text-xs text-red-300 hover:bg-red-500/10">删除</button>
                    </div>
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
