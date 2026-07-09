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
        <div className="max-w-[420px] rounded-2xl rounded-tr-md border border-sky-400/25 bg-[linear-gradient(180deg,rgb(59_130_246_/_20%),rgb(37_99_235_/_13%))] px-4 py-2.5 text-sm text-[var(--as-text-bright)] shadow-[0_8px_22px_rgb(37_99_235_/_18%),inset_0_1px_0_rgb(255_255_255_/_14%)]">
          <MarkdownContent content={message.content} />
        </div>
      ) : (
        <div className="grid w-full max-w-[680px] grid-cols-[28px_minmax(0,1fr)] gap-3">
          <div className="h-7 w-7 rounded-xl bg-[linear-gradient(135deg,#3b82f6,#8b5cf6)] shadow-[0_4px_14px_rgb(99_102_241_/_40%),inset_0_1px_0_rgb(255_255_255_/_30%)]" />
          <div className="min-w-0 border-l border-white/[0.08] pl-4">
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
