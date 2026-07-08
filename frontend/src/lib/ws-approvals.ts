import type { ToolCall } from "@/types";

// 待审批工具的纯逻辑变换：供 sessionStore 复用，避免在 store/hook 内散落数组操作。
// 仿 hooks/ws-reasoning.ts 的抽法（小而纯、零副作用），放在 lib/ 以符合 store→lib 依赖方向。

// 合并新下发的待审批工具：保留已有顺序，仅追加尚未出现（按 id 去重）且带 id 的项。
export const mergePendingApprovals = (existing: ToolCall[], incoming: ToolCall[]): ToolCall[] => {
  const seen = new Set(existing.map((call) => call.id));
  const additions = incoming.filter((call) => call.id && !seen.has(call.id));
  return additions.length ? [...existing, ...additions] : existing;
};

// 决策完成或收到该工具结果后，从待审批列表移除；不存在则原样返回（保持引用稳定）。
export const dropPendingApproval = (list: ToolCall[], toolCallId: string): ToolCall[] =>
  list.some((call) => call.id === toolCallId) ? list.filter((call) => call.id !== toolCallId) : list;
