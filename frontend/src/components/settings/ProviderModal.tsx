import { useEffect, useState } from "react";
import Modal from "@/components/common/Modal";
import { api } from "@/lib/api-client";
import type { Provider } from "@/types";

interface ProviderForm {
  providerType: string;
  name: string;
  baseUrl: string;
  apiKey: string;
  defaultModel: string;
  availableModels: string;
  enabled: boolean;
}
interface Hint {
  ok: boolean;
  message: string;
}
const emptyForm: ProviderForm = { providerType: "openai_compat", name: "", baseUrl: "", apiKey: "", defaultModel: "", availableModels: "", enabled: true };
const toForm = (provider: Provider | null): ProviderForm =>
  provider
    ? {
        providerType: provider.providerType,
        name: provider.name,
        baseUrl: provider.baseUrl,
        apiKey: "",
        defaultModel: provider.defaultModel,
        availableModels: provider.availableModels.join(", "),
        enabled: provider.enabled,
      }
    : emptyForm;
const parseModels = (raw: string): string[] => raw.split(",").map((m) => m.trim()).filter(Boolean);

interface ProviderModalProps {
  isOpen: boolean;
  editing: Provider | null;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
}

export default function ProviderModal({ isOpen, editing, onClose, onSaved }: ProviderModalProps) {
  const [form, setForm] = useState<ProviderForm>(emptyForm);
  const [testState, setTestState] = useState<Hint | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [detected, setDetected] = useState<string[]>([]);
  const [detectState, setDetectState] = useState<Hint | null>(null);
  useEffect(() => {
    if (!isOpen) return;
    setForm(toForm(editing));
    setTestState(null);
    setDetecting(false);
    setDetected([]);
    setDetectState(null);
  }, [isOpen, editing]);
  const selected = parseModels(form.availableModels);
  const toggleModel = (model: string) => {
    setForm((f) => {
      const list = parseModels(f.availableModels);
      const next = list.includes(model) ? list.filter((m) => m !== model) : [...list, model];
      const defaultModel = f.defaultModel || (next.includes(model) ? model : "");
      return { ...f, availableModels: next.join(", "), defaultModel };
    });
  };
  const setAsDefault = (model: string) => {
    setForm((f) => {
      const list = parseModels(f.availableModels);
      return { ...f, defaultModel: model, availableModels: (list.includes(model) ? list : [...list, model]).join(", ") };
    });
  };
  const detectModels = async () => {
    setDetecting(true);
    setDetected([]);
    setDetectState(null);
    try {
      const res = await api.detectModels({
        provider_type: form.providerType,
        base_url: form.baseUrl.trim(),
        api_key: form.apiKey.trim(),
        provider_id: editing?.id ?? null,
      });
      if (res.ok) {
        setDetected(res.models);
        setDetectState({ ok: true, message: `发现 ${res.models.length} 个模型，点击选入可用模型，点 ☆ 设为默认` });
      } else {
        setDetectState({ ok: false, message: `检测失败: ${res.message}` });
      }
    } catch (err) {
      setDetectState({ ok: false, message: `检测失败: ${(err as Error).message}` });
    } finally {
      setDetecting(false);
    }
  };
  const saveProvider = async () => {
    const payload: Record<string, unknown> = {
      name: form.name.trim(),
      provider_type: form.providerType,
      base_url: form.baseUrl.trim(),
      default_model: form.defaultModel.trim(),
      available_models: parseModels(form.availableModels),
      enabled: form.enabled,
    };
    if (form.apiKey.trim() || !editing) payload.api_key = form.apiKey.trim();
    try {
      if (editing) await api.updateProvider(editing.id, payload);
      else await api.addProvider(payload);
      onClose();
      await onSaved();
    } catch (err) {
      setTestState({ ok: false, message: `保存失败: ${(err as Error).message}` });
    }
  };
  const inputCls = "w-full rounded-md border border-[var(--as-border-strong)] bg-[var(--as-bg)] px-3 py-2";
  return (
    <Modal
      isOpen={isOpen}
      title={editing ? "编辑 Provider" : "添加 Provider"}
      onClose={onClose}
      footer={
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-md border border-[var(--as-border-strong)] px-4 py-2 text-sm hover:bg-[var(--as-hover)]">取消</button>
          <button type="button" onClick={() => void saveProvider()} className="as-primary-btn px-4 py-2 text-sm">保存</button>
        </div>
      }
    >
      <div className="space-y-3 text-sm">
        <label className="block"><span className="mb-1 block text-[var(--as-text-secondary)]">Provider 类型</span><select value={form.providerType} onChange={(e) => setForm((f) => ({ ...f, providerType: e.target.value }))} className={inputCls}><option value="openai_compat">OpenAI Compatible</option><option value="anthropic">Anthropic</option><option value="ollama">Ollama</option></select></label>
        <label className="block"><span className="mb-1 block text-[var(--as-text-secondary)]">名称</span><input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} className={inputCls} /></label>
        <label className="block"><span className="mb-1 block text-[var(--as-text-secondary)]">API Base URL</span><input value={form.baseUrl} onChange={(e) => setForm((f) => ({ ...f, baseUrl: e.target.value }))} className={`${inputCls} font-mono`} /></label>
        <label className="block"><span className="mb-1 block text-[var(--as-text-secondary)]">API Key</span><input type="password" value={form.apiKey} onChange={(e) => setForm((f) => ({ ...f, apiKey: e.target.value }))} className={`${inputCls} font-mono`} placeholder={editing ? "留空表示不修改" : ""} /></label>
        <div>
          <div className="flex items-center gap-3">
            <button type="button" onClick={() => void detectModels()} disabled={detecting} className="rounded-md border border-[var(--as-border-strong)] px-3 py-1.5 text-xs hover:bg-[var(--as-hover)] disabled:cursor-not-allowed disabled:opacity-50">{detecting ? "检测中..." : "检测可用模型"}</button>
            {detectState ? <span className={`text-xs ${detectState.ok ? "text-emerald-400" : "text-red-400"}`}>{detectState.message}</span> : null}
          </div>
          {detected.length > 0 ? (
            <div className="mt-2 flex max-h-44 flex-wrap content-start gap-1.5 overflow-y-auto rounded-md border border-[var(--as-border)] bg-[var(--as-bg)] p-2">
              {detected.map((model) => {
                const isSelected = selected.includes(model);
                const isDefault = form.defaultModel === model;
                return (
                  <span key={model} className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 font-mono text-xs ${isSelected ? "border-[var(--as-accent)] bg-[var(--as-hover)] text-[var(--as-text)]" : "border-[var(--as-border-strong)] text-[var(--as-text-secondary)] hover:bg-[var(--as-hover)]"}`}>
                    <button type="button" onClick={() => toggleModel(model)} title={isSelected ? "点击移出可用模型" : "点击加入可用模型"}>{model}</button>
                    <button type="button" onClick={() => setAsDefault(model)} title="设为默认模型" className={isDefault ? "text-amber-400" : "text-[var(--as-text-muted)] hover:text-amber-400"}>{isDefault ? "★" : "☆"}</button>
                  </span>
                );
              })}
            </div>
          ) : null}
        </div>
        <label className="block"><span className="mb-1 block text-[var(--as-text-secondary)]">默认模型</span><input value={form.defaultModel} onChange={(e) => setForm((f) => ({ ...f, defaultModel: e.target.value }))} className={`${inputCls} font-mono`} /></label>
        <label className="block"><span className="mb-1 block text-[var(--as-text-secondary)]">可用模型（逗号分隔）</span><input value={form.availableModels} onChange={(e) => setForm((f) => ({ ...f, availableModels: e.target.value }))} className={`${inputCls} font-mono`} /></label>
        <div className="flex items-center gap-3">
          {editing ? (
            <button
              type="button"
              onClick={() => void api.testProvider(editing.id).then((r) => setTestState({ ok: r.ok, message: r.ok ? `✓ 连接成功 (${r.latency_ms}ms)` : `✗ 连接失败: ${r.message}` })).catch((e) => setTestState({ ok: false, message: `✗ 连接失败: ${(e as Error).message}` }))}
              className="rounded-md border border-[var(--as-border-strong)] px-3 py-1.5 text-xs hover:bg-[var(--as-hover)]"
            >
              测试连接
            </button>
          ) : null}
          {testState ? <span className={`text-xs ${testState.ok ? "text-emerald-400" : "text-red-400"}`}>{testState.message}</span> : null}
        </div>
      </div>
    </Modal>
  );
}
