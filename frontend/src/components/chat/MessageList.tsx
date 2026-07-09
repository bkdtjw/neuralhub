import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { PINNED_THRESHOLD_PX, shouldAutoScroll } from "@/components/chat/auto-scroll";
import MessageBubble from "@/components/chat/MessageBubble";
import ToolCallLine from "@/components/chat/ToolCallLine";
import { useSessionStore } from "@/stores/sessionStore";
import type { AgentStatus, Message } from "@/types";

interface MessageListProps {
  messages: Message[];
  status: AgentStatus;
  streamingText: string;
  streamingReasoning: string;
}

const runningStatuses: AgentStatus[] = ["thinking", "compacting", "tool_calling", "waiting_approval"];

// 容器自带留白 pt-6(24) + pb-56(224)，锚定所需的尾部占位要扣掉这部分
const TAIL_RESERVED_PX = 248;

export default function MessageList({ messages, status, streamingText, streamingReasoning }: MessageListProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const spacerRef = useRef<HTMLDivElement | null>(null);
  const anchorIdRef = useRef<string | null>(null);
  const hydratedRef = useRef(false);
  const prevCountRef = useRef(0);
  const endRef = useRef<HTMLDivElement | null>(null);
  const pinnedRef = useRef(true);
  const prevMessagesRef = useRef<Message[]>(messages);
  const [tailSpacerPx, setTailSpacerPx] = useState(0);
  const [, setMeasureTick] = useState(0);
  const pendingApprovals = useSessionStore((state) => state.pendingApprovals);
  const respondToApproval = useSessionStore((state) => state.respondToApproval);
  const lastError = useSessionStore((state) => state.lastError);
  const visibleMessages = useMemo(() => messages.filter((message) => message.role !== "system"), [messages]);
  const streamingMessage = useMemo<Message | null>(() => {
    if (!streamingText && !streamingReasoning) return null;
    return {
      id: "streaming-assistant",
      role: "assistant",
      content: streamingText,
      reasoningContent: streamingReasoning || undefined,
      timestamp: new Date().toISOString(),
    };
  }, [streamingReasoning, streamingText]);
  const lastAssistantWithTools = useMemo(() => {
    for (let index = visibleMessages.length - 1; index >= 0; index -= 1) {
      const message = visibleMessages[index];
      if (message.role === "assistant" && message.toolCalls?.length) return message.id;
    }
    return null;
  }, [visibleMessages]);

  const lastVisible = visibleMessages[visibleMessages.length - 1];
  const lastUserId = useMemo(() => {
    for (let index = visibleMessages.length - 1; index >= 0; index -= 1) {
      if (visibleMessages[index].role === "user") return visibleMessages[index].id;
    }
    return null;
  }, [visibleMessages]);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < PINNED_THRESHOLD_PX;
  };

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new ResizeObserver(() => setMeasureTick((tick) => tick + 1));
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  // 吸底跟随（审计 F5）：末条为新增 user 消息则无条件吸底，其余仅在用户已贴底时吸底。
  // 与下方"锚定到顶部"并存——锚定后用户已不贴底，故新一轮由锚定效果收尾、流式期间此处不抢滚动。
  useEffect(() => {
    const previous = prevMessagesRef.current;
    prevMessagesRef.current = messages;
    if (!shouldAutoScroll(previous, messages, pinnedRef.current)) return;
    // 流式期间用 "auto"（瞬时）避免平滑动画排队/中断跟随；离散变更用 "smooth"。
    const streaming = Boolean(streamingText || streamingReasoning);
    endRef.current?.scrollIntoView({ behavior: streaming ? "auto" : "smooth", block: "end" });
  }, [messages, status, streamingText, streamingReasoning, pendingApprovals]);

  // 尾部占位：新一轮提问时撑出"锚定到顶部"所需的空间，随生成内容等量收缩（只收不涨），
  // 内容超过一屏后归零；打开历史会话不撑空间，避免拖出大段空白
  useLayoutEffect(() => {
    const container = containerRef.current;
    const spacer = spacerRef.current;
    if (!container || !spacer || !visibleMessages.length) {
      hydratedRef.current = visibleMessages.length > 0;
      anchorIdRef.current = lastUserId;
      if (tailSpacerPx !== 0) setTailSpacerPx(0);
      return;
    }
    if (!hydratedRef.current) {
      hydratedRef.current = true;
      if (!runningStatuses.includes(status)) {
        anchorIdRef.current = lastUserId;
        if (tailSpacerPx !== 0) setTailSpacerPx(0);
        return;
      }
    }
    const anchor = lastUserId ? container.querySelector(`[data-msg-id="${lastUserId}"]`) : null;
    if (!anchor) {
      anchorIdRef.current = lastUserId;
      if (tailSpacerPx !== 0) setTailSpacerPx(0);
      return;
    }
    const contentAfterAnchor = spacer.getBoundingClientRect().top - anchor.getBoundingClientRect().top;
    const needed = Math.max(0, Math.round(container.clientHeight - TAIL_RESERVED_PX - contentAfterAnchor));
    const isNewTurn = lastUserId !== anchorIdRef.current;
    anchorIdRef.current = lastUserId;
    const next = isNewTurn ? needed : Math.min(tailSpacerPx, needed);
    if (Math.abs(next - tailSpacerPx) > 1) setTailSpacerPx(next);
  });

  // 会话切换/首次加载：跳到对话末尾
  useEffect(() => {
    const isInitialFill = prevCountRef.current === 0 && visibleMessages.length > 0;
    prevCountRef.current = visibleMessages.length;
    if (isInitialFill && lastVisible?.role !== "user") {
      const nodes = containerRef.current?.querySelectorAll("[data-msg-id]");
      nodes?.[nodes.length - 1]?.scrollIntoView({ block: "end" });
    }
  }, [visibleMessages.length, lastVisible?.role]);

  // 新一轮提问：把用户消息锚定到视口顶部；之后的生成过程不做任何自动滚动，
  // 思考/工具输出只在锚点下方生长，不会推着视口上下晃
  useEffect(() => {
    if (!lastVisible || lastVisible.role !== "user") return;
    containerRef.current
      ?.querySelector(`[data-msg-id="${lastVisible.id}"]`)
      ?.scrollIntoView({ block: "start" });
  }, [lastVisible?.id, lastVisible?.role]);

  return (
    <div ref={containerRef} onScroll={handleScroll} className="flex-1 overflow-y-auto px-5 pb-56 pt-6">
      <div className="mx-auto w-full max-w-[760px] space-y-[22px]">
        {visibleMessages.map((message) => (
          <div key={message.id} data-msg-id={message.id}>
            <MessageBubble
              message={message}
              isRunning={Boolean(
                lastAssistantWithTools &&
                  message.id === lastAssistantWithTools &&
                  runningStatuses.includes(status),
              )}
            />
          </div>
        ))}
        {streamingMessage ? <MessageBubble message={streamingMessage} isRunning isStreaming /> : null}
        {pendingApprovals.length ? (
          <div className="rounded-lg border border-[var(--as-border-strong)] bg-[var(--as-surface)] p-3">
            <div className="mb-2 text-xs text-[var(--as-text-secondary)]">需要你的审批才能继续</div>
            <div className="space-y-1">
              {pendingApprovals.map((call) => (
                <ToolCallLine
                  key={call.id}
                  call={call}
                  awaitingApproval
                  onApprove={() => respondToApproval(call.id, true)}
                  onReject={() => respondToApproval(call.id, false)}
                />
              ))}
            </div>
          </div>
        ) : null}
        {runningStatuses.includes(status) && !streamingText && !streamingReasoning && !pendingApprovals.length ? (
          <div className="tool-shimmer py-1 text-sm">
            {status === "tool_calling" ? "正在执行工具" : "正在生成"}
          </div>
        ) : null}
        {status === "error" && lastError ? (
          <div className="rounded-lg border border-[#ff7b72] bg-[#451c1c] px-3.5 py-2.5 text-[13px] leading-relaxed text-[#ffd6d3]">
            <div className="mb-0.5 text-xs font-medium text-[#ffb3ae]">运行出错</div>
            <div className="whitespace-pre-wrap break-words">{lastError}</div>
          </div>
        ) : null}
        <div ref={endRef} />
        <div ref={spacerRef} style={{ height: tailSpacerPx }} aria-hidden />
      </div>
    </div>
  );
}
