import { authorizedFetchJson, getApiErrorMessage } from "@/lib/api-auth";

const API_BASE = import.meta.env.VITE_API_BASE || "";

export interface SubAgentTranscriptEntry {
  kind: string;
  content: string;
  is_error: boolean;
  ts: number;
}

export interface SubAgentTranscript {
  role: string;
  stage?: number | null;
  status: string;
  error: string;
  dropped: number;
  started_at: number;
  updated_at: number;
  entries: SubAgentTranscriptEntry[];
}

/** 拉取某次运行里单个子 agent 的完整活动转录（后端进程内存储，重启即失）。 */
export const fetchSubAgentTranscript = async (
  runId: string,
  role: string,
): Promise<SubAgentTranscript> => {
  const url = `${API_BASE}/api/sub-agent-runs/${encodeURIComponent(runId)}/agents/${encodeURIComponent(role)}`;
  const { response, data } = await authorizedFetchJson(url);
  if (!response.ok) throw new Error(getApiErrorMessage(data, response.status));
  return data as SubAgentTranscript;
};
