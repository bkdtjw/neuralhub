import os
import sys


def _bind_addresses() -> list[str]:
    ports = [os.getenv("API_PORT", "8000")]
    ports.extend(os.getenv("API_EXTRA_PORTS", "").split(","))
    seen: set[str] = set()
    addresses: list[str] = []
    for raw_port in ports:
        port = raw_port.strip()
        if not port or port in seen:
            continue
        seen.add(port)
        addresses.append(f"0.0.0.0:{port}")
    return addresses


# 默认单 worker：部分运行时状态仍是【进程内单例】（ProviderManager 配置缓存、
# WebSocket ConnectionManager 的 loop 缓存），多 worker 下会状态分裂——例如在 worker A
# 改了 provider 配置，worker B 的缓存仍是旧值。任务队列/pubsub/会话已走 Redis/PG 可跨
# worker 共享，但上述内存单例尚未做跨 worker 失效，故默认 1；放开需先解决缓存一致性
# （如 Redis pub/sub 失效广播）。详见 DEPLOY.md。
workers = int(os.getenv("GUNICORN_WORKERS") or "1")  # 空串也回落到 1，避免 int("") 崩启动
if workers > 1:
    print(
        "[gunicorn_conf] WARNING: GUNICORN_WORKERS>1 —— ProviderManager/WS loop 缓存为进程内单例，"
        "多 worker 会导致配置状态分裂；除非已接入跨 worker 缓存失效，否则请保持 1。",
        file=sys.stderr,
    )
worker_class = "uvicorn.workers.UvicornWorker"
bind = _bind_addresses()

timeout = 120
graceful_timeout = 30
keepalive = 5

accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")

preload_app = False
