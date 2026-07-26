import { useState } from "react";

import LogResults from "@/components/observability/LogResults";
import LogSearchForm from "@/components/observability/LogSearchForm";
import TraceFlameGraph from "@/components/observability/TraceFlameGraph";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { api } from "@/lib/api-client";
import { observabilityApi } from "@/lib/observability-api";
import type { LogEntry, LogLevel, TraceSpan } from "@/types";

export default function Logs() {
  useDocumentTitle("日志");
  const [query, setQuery] = useState("");
  const [searchType, setSearchType] = useState<"trace" | "session">("trace");
  const [level, setLevel] = useState<LogLevel | "">("");
  const [event, setEvent] = useState("");
  const [component, setComponent] = useState("");
  const [workerId, setWorkerId] = useState("");
  const [errorCode, setErrorCode] = useState("");
  const [minutes, setMinutes] = useState(60);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [title, setTitle] = useState("日志结果");
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [spans, setSpans] = useState<TraceSpan[]>([]);

  const runSearch = async () => {
    const hasMetadataFilter = Boolean(level || event.trim() || component.trim() || workerId.trim() || errorCode.trim());
    if (!query.trim() && !hasMetadataFilter) {
      setError("请输入至少一个日志筛选条件。");
      return;
    }
    try {
      setLoading(true);
      setError("");
      const result = await api.searchLogs({
        traceId: searchType === "trace" ? query.trim() : undefined,
        sessionId: searchType === "session" ? query.trim() : undefined,
        level,
        event: event.trim() || undefined,
        component: component.trim() || undefined,
        workerId: workerId.trim() || undefined,
        errorCode: errorCode.trim() || undefined,
        limit: 100,
        minutes,
      });
      setTitle(
        query.trim()
          ? `${searchType === "trace" ? "trace" : "session"} 检索结果`
          : "多字段检索结果",
      );
      setLogs(result.logs);
      setSpans([]);
    } catch (err) {
      setError((err as Error).message || "搜索失败");
      setLogs([]);
    } finally {
      setLoading(false);
    }
  };

  const loadTrace = async () => {
    if (!query.trim()) {
      setError("请输入 trace_id。");
      return;
    }
    try {
      setLoading(true);
      setError("");
      const [result, spanResult] = await Promise.all([
        api.getTrace(query.trim()),
        observabilityApi.getTraceSpans(query.trim()),
      ]);
      setTitle(`完整调用链 · ${result.traceId}`);
      setLogs(result.events);
      setSpans(spanResult.spans);
    } catch (err) {
      setError((err as Error).message || "加载调用链失败");
      setLogs([]);
      setSpans([]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto bg-[#050505] px-6 py-6 text-[#e6edf3]">
      <section className="mx-auto flex max-w-7xl flex-col gap-6">
        <header className="rounded-3xl border border-[#252525] bg-[radial-gradient(circle_at_top_right,_rgba(210,153,34,0.14),_transparent_32%),linear-gradient(180deg,#0d1117_0%,#070707_100%)] p-6">
          <div className="text-xs uppercase tracking-[0.28em] text-[#7d8590]">Trace Search</div>
          <h1 className="mt-3 text-3xl font-medium text-[#f0f6fc]">日志检索</h1>
          <p className="mt-2 max-w-2xl text-sm text-[#9aa7b2]">按 trace_id 或 session_id 找结构化日志，点击任意一行可以展开完整 JSON。</p>
        </header>

        <LogSearchForm
          query={query}
          searchType={searchType}
          level={level}
          event={event}
          component={component}
          workerId={workerId}
          errorCode={errorCode}
          minutes={minutes}
          loading={loading}
          onQueryChange={setQuery}
          onSearchTypeChange={setSearchType}
          onLevelChange={setLevel}
          onEventChange={setEvent}
          onComponentChange={setComponent}
          onWorkerIdChange={setWorkerId}
          onErrorCodeChange={setErrorCode}
          onMinutesChange={setMinutes}
          onSearch={() => void runSearch()}
          onLoadTrace={() => void loadTrace()}
        />

        {error ? <div className="rounded-2xl border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">{error}</div> : null}
        {loading ? (
          <div className="h-[320px] animate-pulse rounded-3xl border border-[#252525] bg-[#101010]" />
        ) : (
          <>
            <TraceFlameGraph spans={spans} />
            <LogResults logs={logs} title={title} />
          </>
        )}
      </section>
    </div>
  );
}
