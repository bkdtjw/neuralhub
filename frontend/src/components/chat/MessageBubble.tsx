import { memo } from "react";

import MarkdownContent from "@/components/chat/MarkdownContent";
import ReasoningBlock from "@/components/chat/ReasoningBlock";
import ToolCallLine from "@/components/chat/ToolCallLine";
import type { Message, ToolResult } from "@/types";

interface MessageBubbleProps {
  message: Message;
  isRunning?: boolean;
  isStreaming?: boolean;
}

const resultForCall = (results: ToolResult[] | undefined, callId: string, index: number): ToolResult | undefined => {
  if (!results?.length) return undefined;
  return results.find((item) => item.toolCallId && item.toolCallId === callId) ?? results[index];
};

function MessageBubble({ message, isRunning = false, isStreaming = false }: MessageBubbleProps) {
  if (message.role === "tool") return null;

  const isUser = message.role === "user";

  return (
    <div className={`flex w-full ${isUser ? "justify-end" : "justify-start"}`}>
      {isUser ? (
        <div className="max-w-[380px] rounded-[13px] rounded-tr bg-[#1e3a6e] px-4 py-2.5 text-sm text-[var(--as-text)] shadow-[var(--as-user-shadow)] ring-1 ring-[#2a4a86]">
          <MarkdownContent content={message.content} />
        </div>
      ) : (
        <div className="grid max-w-[640px] grid-cols-[26px_minmax(0,1fr)] gap-3">
          <div className="h-[26px] w-[26px] rounded-md bg-[linear-gradient(135deg,#3b82f6,#8b5cf6)]" />
          <div className="max-w-[600px] border-l-2 border-[#1f1f26] pl-4">
            <ReasoningBlock
              content={message.reasoningContent ?? ""}
              durationMs={message.reasoningDurationMs}
              streaming={isStreaming && Boolean(message.reasoningContent)}
            />
            {message.content ? <MarkdownContent content={message.content} /> : null}
            {isStreaming && message.content ? <span className="as-stream-cursor ml-1 inline-block h-4 w-2 align-[-2px]" /> : null}
            {message.toolCalls?.length ? (
              <div className="mt-2 space-y-1">
                {message.toolCalls.map((call, index) => {
                  const result = resultForCall(message.toolResults, call.id, index);
                  return <ToolCallLine key={call.id || index} call={call} result={result} pending={isRunning && !result} />;
                })}
              </div>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}

// memo：历史气泡 props（message 引用/isRunning/isStreaming）在流式期间稳定，跳过重渲；
// 流式气泡因 message 每 token 换新引用仍正常重渲，不影响流式显示。
export default memo(MessageBubble);
