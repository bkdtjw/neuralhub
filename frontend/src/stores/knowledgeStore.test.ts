import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { knowledgeApi } from "@/lib/knowledge-api";
import { useKnowledgeStore } from "@/stores/knowledgeStore";
import type { KnowledgeBase, KnowledgeDocument } from "@/types/knowledge";

vi.mock("@/lib/knowledge-api", () => ({
  knowledgeApi: {
    getStatus: vi.fn(),
    listBases: vi.fn(),
    createBase: vi.fn(),
    renameBase: vi.fn(),
    listDocuments: vi.fn(),
    uploadDocuments: vi.fn(),
  },
}));

const doc = (id: string, status: KnowledgeDocument["status"]): KnowledgeDocument => ({
  id,
  kbId: "kb1",
  filename: `${id}.md`,
  fileType: "md",
  fileSize: 1024,
  chunkCount: 0,
  status,
  error: "",
  createdAt: "2026-07-26T00:00:00Z",
});

const base = (id: string): KnowledgeBase => ({
  id,
  name: id,
  description: "",
  createdAt: "2026-07-26T00:00:00Z",
  documentCount: 0,
  chunkCount: 0,
});

describe("knowledgeStore 文档新鲜度轮询与新建库残留清理", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    vi.mocked(knowledgeApi.listBases).mockResolvedValue([base("kb1")]);
    useKnowledgeStore.setState({ bases: [base("kb1")], currentKbId: "kb1", documents: [], error: "", loading: false });
  });

  afterEach(() => {
    useKnowledgeStore.getState().stopPolling();
    vi.useRealTimers();
  });

  it("存在 processing 文档时起 4s 轮询，全部到达终态后自动停表", async () => {
    vi.mocked(knowledgeApi.listDocuments).mockResolvedValueOnce([doc("a", "processing")]);
    await useKnowledgeStore.getState().loadDocuments("kb1");
    expect(knowledgeApi.listDocuments).toHaveBeenCalledTimes(1);

    vi.mocked(knowledgeApi.listDocuments).mockResolvedValue([doc("a", "ready")]);
    await vi.advanceTimersByTimeAsync(4000);
    expect(knowledgeApi.listDocuments).toHaveBeenCalledTimes(2);
    expect(knowledgeApi.listBases).toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(20000);
    expect(knowledgeApi.listDocuments).toHaveBeenCalledTimes(2);
  });

  it("重复触发 loadDocuments 不会重复起表（同一 4s 窗口只多打一次）", async () => {
    vi.mocked(knowledgeApi.listDocuments).mockResolvedValue([doc("a", "processing")]);
    await useKnowledgeStore.getState().loadDocuments("kb1");
    await useKnowledgeStore.getState().loadDocuments("kb1");
    expect(knowledgeApi.listDocuments).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(4000);
    expect(knowledgeApi.listDocuments).toHaveBeenCalledTimes(3);
  });

  it("stopPolling 清理轮询（页面卸载防泄漏）", async () => {
    vi.mocked(knowledgeApi.listDocuments).mockResolvedValue([doc("a", "processing")]);
    await useKnowledgeStore.getState().loadDocuments("kb1");
    useKnowledgeStore.getState().stopPolling();

    await vi.advanceTimersByTimeAsync(20000);
    expect(knowledgeApi.listDocuments).toHaveBeenCalledTimes(1);
  });

  it("createBase 成功后先清空旧库文档再拉新库，杜绝残留列表", async () => {
    useKnowledgeStore.setState({ documents: [doc("old", "ready")], currentKbId: "kb1" });
    vi.mocked(knowledgeApi.createBase).mockResolvedValue(base("kb-new"));
    let documentsWhenLoading: KnowledgeDocument[] | null = null;
    vi.mocked(knowledgeApi.listDocuments).mockImplementation(async () => {
      documentsWhenLoading = useKnowledgeStore.getState().documents;
      return [];
    });

    await useKnowledgeStore.getState().createBase("新库");

    expect(documentsWhenLoading).toEqual([]);
    expect(knowledgeApi.listDocuments).toHaveBeenCalledWith("kb-new");
    expect(useKnowledgeStore.getState().currentKbId).toBe("kb-new");
    expect(useKnowledgeStore.getState().documents).toEqual([]);
  });
});
