import { useEffect, useMemo, useState } from "react";

import CacheHitTrend from "@/components/observability/CacheHitTrend";
import MetricCard from "@/components/observability/MetricCard";
import MetricsTrend from "@/components/observability/MetricsTrend";
import { api } from "@/lib/api-client";
import { observabilityApi } from "@/lib/observability-api";
import type { LatencySummary, MetricsSummary } from "@/types";

const dayOptions = [7, 14, 30];
const REFRESH_INTERVAL_MS = 30_000;

const formatCompact = (value: number) =>
  value >= 1000 ? `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}K` : String(value);
const formatMs = (value: number) => (value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${Math.round(value)}ms`);

interface MetricCardData {
  title: string;
  value: number | string;
  note: string;
  tone?: "default" | "danger";
}

const emptySummary = (days: number): MetricsSummary => ({
  periodDays: days,
  metrics: {
    agent_runs: { total: 0, daily: {} },
    feishu_messages: { total: 0, daily: {} },
    feishu_replies: { total: 0, daily: {} },
    llm_cache_creation_tokens: { total: 0, daily: {} },
    llm_calls: { total: 0, daily: {} },
    llm_cached_prompt_tokens: { total: 0, daily: {} },
    llm_completion_tokens: { total: 0, daily: {} },
    llm_errors: { total: 0, daily: {} },
    llm_prompt_tokens: { total: 0, daily: {} },
    task_failures: { total: 0, daily: {} },
    task_successes: { total: 0, daily: {} },
    task_triggers: { total: 0, daily: {} },
    tool_calls: { total: 0, daily: {} },
    tool_errors: { total: 0, daily: {} },
  },
});

const emptyLatency = (): LatencySummary => ({ latencies: {} });

export default function Metrics() {
  const [days, setDays] = useState(7);
  const [summary, setSummary] = useState<MetricsSummary>(emptySummary(7));
  const [latency, setLatency] = useState<LatencySummary>(emptyLatency());
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    const load = async (showLoading: boolean) => {
      try {
        if (showLoading) {
          setLoading(true);
          setLoaded(false);
        }
        setError("");
        const [metricsSummary, latencySummary] = await Promise.all([
          api.getMetricsSummary(days),
          observabilityApi.getLatencySummary(days),
        ]);
        if (cancelled) return;
        setSummary(metricsSummary);
        setLatency(latencySummary);
        setLoaded(true);
      } catch (err) {
        if (cancelled) return;
        setError((err as Error).message || "加载指标失败");
      } finally {
        if (!cancelled && showLoading) setLoading(false);
      }
    };

    void load(true);
    const timer = window.setInterval(() => void load(false), REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [days]);

  const labels = useMemo(() => Object.keys(summary.metrics.llm_calls.daily), [summary]);
  const llmCalls = labels.map((label) => summary.metrics.llm_calls.daily[label] ?? 0);
  const agentRuns = labels.map((label) => summary.metrics.agent_runs.daily[label] ?? 0);
  // 缓存命中率口径：命中 = cache_read；未命中 = 未走缓存的输入 + 首写缓存(cache_creation)。
  const cacheHits = labels.map((label) => summary.metrics.llm_cached_prompt_tokens.daily[label] ?? 0);
  const cacheMisses = labels.map(
    (label) =>
      (summary.metrics.llm_prompt_tokens.daily[label] ?? 0) +
      (summary.metrics.llm_cache_creation_tokens?.daily?.[label] ?? 0),
  );
  const cacheHitTotal = summary.metrics.llm_cached_prompt_tokens.total;
  const cacheInputTotal =
    cacheHitTotal + summary.metrics.llm_prompt_tokens.total + (summary.metrics.llm_cache_creation_tokens?.total ?? 0);

  const cards: MetricCardData[] = [
    { title: "Agent 执行", value: summary.metrics.agent_runs.total, note: `最近 ${days} 天总执行次数` },
    { title: "LLM 调用", value: summary.metrics.llm_calls.total, note: `错误 ${summary.metrics.llm_errors.total}`, tone: summary.metrics.llm_errors.total > 0 ? "danger" : "default" },
    { title: "工具调用", value: summary.metrics.tool_calls.total, note: `错误 ${summary.metrics.tool_errors.total}`, tone: summary.metrics.tool_errors.total > 0 ? "danger" : "default" },
    { title: "定时任务", value: summary.metrics.task_triggers.total, note: `成功 ${summary.metrics.task_successes.total} / 失败 ${summary.metrics.task_failures.total}`, tone: summary.metrics.task_failures.total > 0 ? "danger" : "default" },
    { title: "Token 用量", value: `${formatCompact(summary.metrics.llm_prompt_tokens.total)}/${formatCompact(summary.metrics.llm_completion_tokens.total)}`, note: "输入 / 输出" },
    { title: "缓存命中率", value: cacheInputTotal > 0 ? `${Math.round((cacheHitTotal / cacheInputTotal) * 100)}%` : "—", note: `命中 ${formatCompact(cacheHitTotal)} / 输入 ${formatCompact(cacheInputTotal)}` },
    { title: "飞书消息", value: summary.metrics.feishu_messages.total, note: `回复 ${summary.metrics.feishu_replies.total}` },
  ];
  const latencyCards = Object.entries(latency.latencies).map(([key, item]) => ({
    key,
    title: `${item.name} P95`,
    value: formatMs(item.p95_ms),
    note: `样本 ${item.count} · max ${formatMs(item.max_ms)}`,
    tone: item.p95_ms > 30000 ? "danger" as const : "default" as const,
  }));

  return (
    <div className="h-full overflow-y-auto bg-[#050505] px-6 py-6 text-[#e6edf3]">
      <section className="mx-auto flex max-w-7xl flex-col gap-6">
        <header className="flex flex-col gap-4 rounded-3xl border border-[#252525] bg-[radial-gradient(circle_at_top_left,_rgba(88,166,255,0.15),_transparent_35%),linear-gradient(180deg,#0d1117_0%,#070707_100%)] p-6 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.28em] text-[#7d8590]">Observability</div>
            <h1 className="mt-3 text-3xl font-medium text-[#f0f6fc]">系统概览</h1>
            <p className="mt-2 max-w-2xl text-sm text-[#9aa7b2]">这里直接读 Redis 指标汇总，适合快速看调用量、失败量和 Token 消耗。</p>
          </div>
          <label className="text-sm text-[#9aa7b2]">
            <span className="mb-2 block">时间范围</span>
            <select value={days} onChange={(event) => setDays(Number(event.target.value))} className="rounded-2xl border border-[#2c2c2c] bg-[#050505] px-4 py-3 text-sm text-[#f0f6fc]">
              {dayOptions.map((value) => (
                <option key={value} value={value}>
                  最近 {value} 天
                </option>
              ))}
            </select>
          </label>
        </header>

        {error ? <div className="rounded-2xl border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">{error}</div> : null}

        {loading ? (
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }, (_, index) => (
              <div key={index} className="h-[136px] animate-pulse rounded-2xl border border-[#252525] bg-[#101010]" />
            ))}
          </section>
        ) : null}

        {!loading && loaded ? (
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {cards.map((card) => (
              <MetricCard
                key={card.title}
                title={card.title}
                value={typeof card.value === "number" ? formatCompact(card.value) : card.value}
                note={card.note}
                tone={card.tone}
              />
            ))}
          </section>
        ) : null}

        {loading ? (
          <div className="h-[300px] animate-pulse rounded-3xl border border-[#252525] bg-[#101010]" />
        ) : loaded ? (
          <MetricsTrend labels={labels} agentRuns={agentRuns} llmCalls={llmCalls} />
        ) : null}

        {loading ? (
          <div className="h-[300px] animate-pulse rounded-3xl border border-[#252525] bg-[#101010]" />
        ) : loaded ? (
          <CacheHitTrend labels={labels} hitTokens={cacheHits} missTokens={cacheMisses} />
        ) : null}

        {!loading && loaded && latencyCards.length ? (
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {latencyCards.map((card) => (
              <MetricCard
                key={card.key}
                title={card.title}
                value={card.value}
                note={card.note}
                tone={card.tone}
              />
            ))}
          </section>
        ) : null}
      </section>
    </div>
  );
}
