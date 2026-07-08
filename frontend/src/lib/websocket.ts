import { normalizeWsIncoming } from "@/lib/websocket-normalize";
import type { WsIncoming } from "@/types";

type Handler = (payload: unknown) => void;

const WS_BASE = import.meta.env.VITE_WS_BASE || "";
const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;
// 连续退避重连累计达到该次数仍未成功 → emit "give-up"，让 UI 切到“已断开，可手动重连”；
// 但后台仍无限退避重连，后端恢复后自愈（原先满 3 次即彻底放弃）。
const GIVE_UP_AFTER_ATTEMPTS = 5;

class AgentWebSocket {
  private ws: WebSocket | null = null;
  private connectPromise: Promise<void> | null = null;
  private handlers: Map<string, Handler[]> = new Map();
  private reconnectAttempts = 0;
  private sessionId: string | null = null;
  private socketSessionId: string | null = null;
  private manuallyClosed = false;
  private connectVersion = 0;
  private reconnectTimer: number | null = null;

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private isActiveSocket(socket: WebSocket, version: number): boolean {
    return this.ws === socket && this.connectVersion === version;
  }

  connect(sessionId: string): Promise<void> {
    this.sessionId = sessionId;
    this.manuallyClosed = false;
    this.clearReconnectTimer();

    if (this.ws && this.ws.readyState === WebSocket.OPEN && this.socketSessionId === sessionId) {
      return Promise.resolve();
    }

    if (this.connectPromise && this.socketSessionId === sessionId) {
      return this.connectPromise;
    }

    this.connectVersion += 1;
    const version = this.connectVersion;
    const previousSocket = this.ws;
    this.ws = null;
    this.socketSessionId = null;
    this.connectPromise = null;
    if (previousSocket) previousSocket.close();

    this.connectPromise = new Promise<void>((resolve, reject) => {
      let timeoutId = 0;
      let settled = false;
      let url: string;

      if (WS_BASE) {
        url = `${WS_BASE}/ws/${encodeURIComponent(sessionId)}`;
      } else {
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        url = `${protocol}//${window.location.host}/ws/${encodeURIComponent(sessionId)}`;
      }

      const socket = new WebSocket(url);
      this.ws = socket;
      this.socketSessionId = sessionId;

      const resolveOnce = () => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timeoutId);
        if (this.connectPromise && this.connectVersion === version) {
          this.connectPromise = null;
        }
        resolve();
      };

      const rejectOnce = (error: Error) => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timeoutId);
        if (this.connectPromise && this.connectVersion === version) {
          this.connectPromise = null;
        }
        reject(error);
      };

      socket.onopen = () => {
        if (!this.isActiveSocket(socket, version)) {
          socket.close();
          rejectOnce(new Error("Stale WebSocket connection"));
          return;
        }
        // 断线重连成功（reconnectAttempts>0）时带出 reconnected=true，供上层做非破坏性 resync；
        // 必须在重置 reconnectAttempts 之前取值，否则首连也会误触发补偿、覆盖刚乐观 set 的 user 消息。
        this.emit("open", { reconnected: this.reconnectAttempts > 0 });
        this.reconnectAttempts = 0;
        resolveOnce();
      };

      socket.onmessage = (event) => {
        if (!this.isActiveSocket(socket, version)) return;
        try {
          const raw = JSON.parse(event.data) as Record<string, unknown>;
          const parsed = normalizeWsIncoming(raw);
          this.emit(parsed.type, parsed);
        } catch {
          this.emit("error", { type: "error", message: "Invalid WebSocket payload" } as WsIncoming);
        }
      };

      socket.onerror = (event) => {
        if (!this.isActiveSocket(socket, version)) return;
        this.emit("error", event);
      };

      socket.onclose = (event) => {
        if (!this.isActiveSocket(socket, version)) {
          rejectOnce(new Error("WebSocket closed before connect"));
          return;
        }
        this.emit("close", event);
        this.ws = null;
        this.socketSessionId = null;
        if (!settled) {
          rejectOnce(new Error("WebSocket closed before connect"));
        }
        if (this.manuallyClosed || !this.sessionId) return;
        // 无限次重连 + 指数退避封顶 30s：后端重启 / >7s 抖动后仍能自愈。
        const delay = Math.min(RECONNECT_BASE_MS * 2 ** this.reconnectAttempts, RECONNECT_MAX_MS);
        this.reconnectAttempts += 1;
        // 长时间断开（累计到阈值仍未连上）：emit give-up 让 UI 提供手动重连入口；后台仍继续退避重连。
        if (this.reconnectAttempts === GIVE_UP_AFTER_ATTEMPTS) {
          this.emit("give-up", { attempts: this.reconnectAttempts });
        }
        this.reconnectTimer = window.setTimeout(() => {
          void this.connect(this.sessionId as string);
        }, delay);
      };

      timeoutId = window.setTimeout(() => {
        if (socket.readyState !== WebSocket.OPEN) {
          if (this.isActiveSocket(socket, version)) {
            socket.close();
          }
          rejectOnce(new Error("WebSocket connect timeout"));
        }
      }, 5000);
    });

    return this.connectPromise;
  }

  send(data: { type: string; [key: string]: unknown }): boolean {
    const socket = this.ws;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      console.warn("WebSocket is not connected, skip send:", data.type, socket?.readyState ?? "null");
      return false;
    }
    socket.send(JSON.stringify(data));
    return true;
  }

  on(type: string, handler: Handler): void {
    const list = this.handlers.get(type) ?? [];
    list.push(handler);
    this.handlers.set(type, list);
  }

  off(type: string, handler: Handler): void {
    const list = this.handlers.get(type);
    if (!list) return;
    this.handlers.set(type, list.filter((item) => item !== handler));
  }

  close(): void {
    this.manuallyClosed = true;
    this.reconnectAttempts = 0;
    this.connectVersion += 1;
    this.clearReconnectTimer();
    this.connectPromise = null;
    this.socketSessionId = null;
    const socket = this.ws;
    this.ws = null;
    if (socket) socket.close();
  }

  private emit(type: string, payload: unknown): void {
    const list = this.handlers.get(type) ?? [];
    for (const handler of list) handler(payload);
  }
}

export const agentWs = new AgentWebSocket();
