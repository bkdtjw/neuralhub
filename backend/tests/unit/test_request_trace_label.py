from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.api.middleware.request_trace import _route_path


@pytest.fixture(autouse=True)
def bind_test_database() -> None:  # 覆盖 conftest 的 autouse DB 绑定，跳过 PostgresContainer
    yield


def _fake_request(route_path: str | None, url_path: str):
    route = SimpleNamespace(path=route_path) if route_path is not None else None
    return SimpleNamespace(scope={"route": route}, url=SimpleNamespace(path=url_path))


def test_matched_route_uses_registered_template():
    # 已注册路由：用路由模板作 label（有界，label 基数受路由数上限约束）
    request = _fake_request("/api/sessions/{session_id}", "/api/sessions/abc123")
    assert _route_path(request) == "/api/sessions/{session_id}"


def test_unmatched_route_collapses_to_constant():
    # 未匹配路由（404 / 公网扫描 /.env、/wp-admin 等）一律归到固定常量，
    # 避免每个随机 URL 生成新 Prometheus label 组合导致基数无限膨胀。
    for scanned in ["/.env", "/wp-admin/setup-config.php", "/random/xyz", "/"]:
        request = _fake_request(None, scanned)
        assert _route_path(request) == "unmatched"


def test_route_without_path_attr_collapses_to_constant():
    request = _fake_request("", "/whatever")
    assert _route_path(request) == "unmatched"
