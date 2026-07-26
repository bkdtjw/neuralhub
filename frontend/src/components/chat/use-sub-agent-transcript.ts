import { useCallback, useEffect, useState } from "react";

import { fetchSubAgentTranscript } from "@/lib/sub-agent-api";
import type { SubAgentTranscript } from "@/lib/sub-agent-api";

// 正常轮询间隔；拉取失败后改为退避重试（3s 起每次 ×1.5，上限 10s），成功即恢复正常节奏。
const POLL_MS = 2000;
const RETRY_BASE_MS = 3000;
const RETRY_FACTOR = 1.5;
const RETRY_MAX_MS = 10_000;

const isActive = (status: string): boolean => status === "pending" || status === "running";

export interface SubAgentTranscriptPoll {
  transcript: SubAgentTranscript | null;
  fetchError: string;
  /** 最近一次成功拉取的本地时间戳（ms），0 表示尚未成功过。 */
  updatedAt: number;
  /** 手动重拉：重置退避并立即请求一次。 */
  refresh: () => void;
}

/**
 * 轮询单个子 agent 的完整转录。
 * 失败不断链：只要子 agent 仍在 pending/running，就按指数退避继续重试，
 * 避免一次网络抖动导致转录永久停更。
 */
export function useSubAgentTranscript(rawRunId: string, role: string, agentStatus: string): SubAgentTranscriptPoll {
  const [transcript, setTranscript] = useState<SubAgentTranscript | null>(null);
  const [fetchError, setFetchError] = useState("");
  const [updatedAt, setUpdatedAt] = useState(0);
  const [reloadTick, setReloadTick] = useState(0);

  useEffect(() => {
    if (!rawRunId) {
      setFetchError("该运行缺少 run_id，无法查询完整转录");
      return;
    }
    let closed = false;
    let timer: number | undefined;
    let retryDelay = RETRY_BASE_MS;
    let lastStatus = agentStatus;
    const load = async (): Promise<void> => {
      try {
        const data = await fetchSubAgentTranscript(rawRunId, role);
        if (closed) return;
        lastStatus = data.status;
        retryDelay = RETRY_BASE_MS;
        setTranscript(data);
        setFetchError("");
        setUpdatedAt(Date.now());
        if (isActive(data.status)) timer = window.setTimeout(() => void load(), POLL_MS);
      } catch (error) {
        if (closed) return;
        setFetchError(error instanceof Error ? error.message : String(error));
        if (isActive(lastStatus)) {
          timer = window.setTimeout(() => void load(), retryDelay);
          retryDelay = Math.min(Math.round(retryDelay * RETRY_FACTOR), RETRY_MAX_MS);
        }
      }
    };
    void load();
    return () => {
      closed = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [rawRunId, role, agentStatus, reloadTick]);

  const refresh = useCallback(() => setReloadTick((value) => value + 1), []);

  return { transcript, fetchError, updatedAt, refresh };
}
