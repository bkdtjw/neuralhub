import { useEffect, useMemo, useRef } from "react";

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

export default function MessageList({ messages, status, streamingText, streamingReasoning }: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  const pinnedRef = useRef(true);
  const prevMessagesRef = useRef<Message[]>(messages);
  const pendingApprovals = useSessionStore((state) => state.pendingApprovals);
  const respondToApproval = useSessionStore((state) => state.respondToApproval);
  const lastError = useSessionStore((state) => state.lastError);
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
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index];
      if (message.role === "assistant" && message.toolCalls?.length) return message.id;
    }
    return null;
  }, [messages]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < PINNED_THRESHOLD_PX;
  };

  useEffect(() => {
    const previous = prevMessagesRef.current;
    prevMessagesRef.current = messages;
    if (!shouldAutoScroll(previous, messages, pinnedRef.current)) return;
    // 流式期间用 "auto"（瞬时）避免平滑动画排队/中断跟随；离散变更用 "smooth"。
    const streaming = Boolean(streamingText || streamingReasoning);
    endRef.current?.scrollIntoView({ behavior: streaming ? "auto" : "smooth", block: "end" });
  }, [messages, status, streamingText, streamingReasoning, pendingApprovals]);

  return (
    <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto px-5 pb-56 pt-6">
      <div className="mx-auto w-full max-w-[760px] space-y-[22px]">
        {messages.map((message) => (
          <MessageBubble
            key={message.id}
            message={message}
            isRunning={Boolean(
              lastAssistantWithTools &&
                message.id === lastAssistantWithTools &&
                runningStatuses.includes(status),
            )}
          />
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
      </div>
    </div>
  );
}
