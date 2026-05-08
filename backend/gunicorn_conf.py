import os


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


workers = int(os.getenv("GUNICORN_WORKERS", "4"))
worker_class = "uvicorn.workers.UvicornWorker"
bind = _bind_addresses()

timeout = 120
graceful_timeout = 30
keepalive = 5

accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")

preload_app = False
