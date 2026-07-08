import { useSessionStore } from "@/stores/sessionStore";

// 断线补偿：把 agentWs 的连接生命周期事件映射到 sessionStore.connectionState，
// 并在“重连成功”（reconnected=true）时触发非破坏性 resync，找回断线期间丢失的消息/终态。
// 独立成模块（仿 ws-reasoning.ts），避免 useWebSocket 继续膨胀。
export interface ConnectionHandlers {
  onOpen: (payload: unknown) => void;
  onClose: () => void;
  onGiveUp: () => void;
}

export const createConnectionHandlers = (sessionId: string): ConnectionHandlers => ({
  onOpen: (payload: unknown) => {
    const reconnected = Boolean((payload as { reconnected?: boolean } | null)?.reconnected);
    const store = useSessionStore.getState();
    store.setConnectionState("connected");
    // 仅重连成功才补偿；首连 reconnected=false，避免覆盖刚乐观 set 的 user 消息。
    if (reconnected) void store.resync(sessionId);
  },
  onClose: () => {
    const store = useSessionStore.getState();
    // give-up 后已是 disconnected 就保持，避免后续每次退避失败又闪回 reconnecting、令手动重连入口消失。
    if (store.connectionState !== "disconnected") store.setConnectionState("reconnecting");
  },
  onGiveUp: () => {
    useSessionStore.getState().setConnectionState("disconnected");
  },
});
