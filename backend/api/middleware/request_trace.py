from __future__ import annotations

from time import monotonic

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from backend.common.errors import AgentError
from backend.common.logging import bound_log_context, get_logger, new_trace_id
from backend.common.metrics import record_latency_sample
from backend.common.prometheus_metrics import observe_http_request
from backend.common.tracing import trace_context, trace_span

TRACE_HEADER = "X-Trace-Id"
logger = get_logger(component="request_trace")


class RequestTraceError(AgentError):
    pass


class RequestTraceMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        trace_id = _trace_id_from_request(request)
        started_at = monotonic()
        with bound_log_context(
            trace_id=trace_id,
            method=request.method,
            path=request.url.path,
        ), trace_context(trace_id), trace_span(
            "http.request",
            {"method": request.method, "path": request.url.path},
        ) as span:
            try:
                response = await call_next(request)
                path = _route_path(request)
                duration_seconds = monotonic() - started_at
                span.set_attribute("path", path)
                span.set_attribute("status_code", response.status_code)
                response.headers[TRACE_HEADER] = trace_id
                observe_http_request(request.method, path, response.status_code, duration_seconds)
                await record_latency_sample("http", int(duration_seconds * 1000))
                logger.debug(
                    "http_request_end",
                    status_code=response.status_code,
                    duration_ms=int(duration_seconds * 1000),
                )
                return response
            except Exception as exc:  # noqa: BLE001
                duration_seconds = monotonic() - started_at
                span.set_attribute("status_code", 500)
                observe_http_request(request.method, _route_path(request), 500, duration_seconds)
                await record_latency_sample("http", int(duration_seconds * 1000))
                logger.exception(
                    "http_request_error",
                    duration_ms=int(duration_seconds * 1000),
                )
                raise RequestTraceError("REQUEST_TRACE_ERROR", str(exc)) from exc


def _trace_id_from_request(request: Request) -> str:
    value = request.headers.get(TRACE_HEADER, "").strip()
    return value or new_trace_id()


def _route_path(request: Request) -> str:
    # 只把【已注册的路由模板】作为指标 label，未匹配路由（404、公网扫描 /.env、/wp-admin 等）
    # 一律归到固定常量，否则每个随机 URL 都会生成新 label 组合（Prometheus Counter/Histogram
    # 永不回收），长时间运行 label 基数无限膨胀 → 内存持续增长直至 OOM。
    route = request.scope.get("route")
    path = getattr(route, "path", "")
    return str(path) if path else "unmatched"


__all__ = ["RequestTraceError", "RequestTraceMiddleware", "TRACE_HEADER"]
