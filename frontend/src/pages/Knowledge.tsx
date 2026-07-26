import { type ChangeEvent, useEffect, useRef } from "react";
import { Database, Pencil, Plus, Upload } from "lucide-react";

import EmptyState from "@/components/common/EmptyState";
import { useKnowledgeStore } from "@/stores/knowledgeStore";
import type { KnowledgeDocument } from "@/types/knowledge";

export default function Knowledge() {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const bases = useKnowledgeStore((state) => state.bases);
  const currentKbId = useKnowledgeStore((state) => state.currentKbId);
  const documents = useKnowledgeStore((state) => state.documents);
  const loading = useKnowledgeStore((state) => state.loading);
  const uploading = useKnowledgeStore((state) => state.uploading);
  const error = useKnowledgeStore((state) => state.error);
  const loadAll = useKnowledgeStore((state) => state.loadAll);
  const createBase = useKnowledgeStore((state) => state.createBase);
  const renameCurrentBase = useKnowledgeStore((state) => state.renameCurrentBase);
  const setCurrentKbId = useKnowledgeStore((state) => state.setCurrentKbId);
  const uploadDocuments = useKnowledgeStore((state) => state.uploadDocuments);
  const current = bases.find((item) => item.id === currentKbId) ?? bases[0] ?? null;

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const create = async () => {
    const name = window.prompt("新知识库名称");
    if (name?.trim()) await createBase(name);
  };

  const rename = async () => {
    const name = window.prompt("重命名知识库", current?.name ?? "");
    if (name?.trim()) await renameCurrentBase(name);
  };

  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    await uploadDocuments(files);
  };

  return (
    <div className="h-full overflow-y-auto bg-[var(--as-bg)] px-6 py-6">
      <div className="mx-auto grid max-w-6xl gap-5 lg:grid-cols-[260px_1fr]">
        <aside className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface-low)] p-3">
          <div className="mb-3 flex items-center justify-between">
            <div className="text-sm font-medium text-[var(--as-text)]">知识库</div>
            <button type="button" onClick={() => void create()} className="as-primary-btn h-8 px-2.5 text-xs">
              <Plus size={14} />
              新建
            </button>
          </div>
          <div className="space-y-1">
            {bases.map((base) => (
              <button
                key={base.id}
                type="button"
                onClick={() => setCurrentKbId(base.id)}
                className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm ${
                  base.id === currentKbId ? "bg-[var(--as-active)] text-[var(--as-text)]" : "text-[var(--as-text-secondary)] hover:bg-[var(--as-hover)]"
                }`}
              >
                <Database size={15} />
                <span className="min-w-0 flex-1 truncate">{base.name}</span>
                <span className="text-[11px] text-[var(--as-text-muted)]">{base.documentCount}</span>
              </button>
            ))}
          </div>
        </aside>
        <main className="min-w-0 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface-low)] p-5">
          <header className="flex flex-col gap-3 border-b border-[var(--as-border)] pb-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h1 className="text-lg font-medium text-[var(--as-text-bright)]">{current?.name ?? "暂无知识库"}</h1>
              <p className="mt-1 text-xs text-[var(--as-text-muted)]">
                {current ? `${current.documentCount} 个文档 · ${current.chunkCount} 段` : "创建知识库后即可上传资料"}
              </p>
            </div>
            <div className="flex gap-2">
              <button type="button" disabled={!current} onClick={() => void rename()} className="as-select inline-flex h-9 items-center gap-1.5">
                <Pencil size={14} />
                重命名
              </button>
              <button type="button" disabled={!current || uploading} onClick={() => fileInputRef.current?.click()} className="as-primary-btn h-9 gap-1.5 px-3 text-sm disabled:opacity-45">
                <Upload size={15} />
                {uploading ? "上传中" : "上传文件"}
              </button>
            </div>
          </header>
          {error ? <div className="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">{error}</div> : null}
          {loading ? (
            <div className="mt-5 h-40 animate-pulse rounded-xl bg-[var(--as-surface)]" />
          ) : current ? (
            <DocumentTable documents={documents} />
          ) : (
            <div className="flex justify-center py-10">
              <div className="w-full max-w-[400px]">
                <EmptyState
                  icon={Database}
                  title="还没有知识库"
                  description="新建一个知识库并上传文档，会话即可引用这些资料"
                  action={{ label: "新建知识库", onClick: () => void create() }}
                />
              </div>
            </div>
          )}
        </main>
      </div>
      <input ref={fileInputRef} type="file" multiple accept=".pdf,.docx,.md,.txt" className="hidden" onChange={(event) => void upload(event)} />
    </div>
  );
}

function DocumentTable({ documents }: { documents: KnowledgeDocument[] }) {
  if (!documents.length) return <div className="py-14 text-center text-sm text-[var(--as-text-muted)]">当前知识库还没有文档</div>;
  return (
    <div className="mt-5 overflow-hidden rounded-xl border border-[var(--as-border)]">
      {documents.map((doc) => (
        <div key={doc.id} className="grid grid-cols-[1fr_96px_80px] items-center gap-3 border-b border-[var(--as-border)] px-4 py-3 last:border-b-0">
          <div className="min-w-0">
            <div className="truncate text-sm text-[var(--as-text)]">{doc.filename}</div>
            <div className="mt-1 truncate text-xs text-[var(--as-text-muted)]">{doc.error || `${doc.fileType.toUpperCase()} · ${formatBytes(doc.fileSize)}`}</div>
          </div>
          <span className={`rounded-md px-2 py-1 text-center text-xs ${statusClass(doc.status)}`}>{statusLabel(doc.status)}</span>
          <span className="text-right font-mono text-xs text-[var(--as-text-muted)]">{doc.chunkCount} 段</span>
        </div>
      ))}
    </div>
  );
}

const statusLabel = (status: KnowledgeDocument["status"]): string => ({ processing: "处理中", ready: "已入库", partial: "部分成功", failed: "失败", empty: "空内容" })[status];
const statusClass = (status: KnowledgeDocument["status"]): string =>
  status === "ready" ? "bg-emerald-500/15 text-emerald-300" : status === "processing" ? "bg-blue-500/15 text-blue-300" : "bg-yellow-500/15 text-yellow-200";
const formatBytes = (bytes: number): string => (bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);
