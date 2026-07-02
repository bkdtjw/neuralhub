from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.config.settings import settings
from backend.core.s02_tools.builtin.x_models import XClientConfig, XPost
from backend.core.s07_task_system import event_hooks as eh
from backend.core.s07_task_system import event_hooks_runtime as runtime_module
from backend.core.s07_task_system.event_hooks_runtime import HookRuntime, build_hook_runtime, make_assess_fn, make_push_fn, make_twitter_search_fn
from backend.core.s07_task_system.event_hooks_runtime import push as push_module
from backend.core.s07_task_system.event_hooks_runtime import twitter as twitter_module

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def bind_test_database() -> None:
    return None


def _x_config() -> XClientConfig:
    return XClientConfig(username="user", email="e@test", password="secret")


def _post(text: str = "Update") -> XPost:
    return XPost(
        author_name="Reporter", author_handle="reporter", text=text, likes=4,
        retweets=3, replies=1, views=100, created_at="2026-06-27T00:00:00Z",
        url="https://x.com/reporter/status/1",
    )


def _hook() -> eh.EventHook:
    return eh.EventHook(
        id="hook-1", name="Launch Watch",
        twitter=eh.HookTwitterConfig(accounts=["newsdesk"], keywords=["launch"]),
        sources=eh.HookSources(), cadence_minutes=45, materiality=60,
        enabled=True, created_at="2026-06-27T00:00:00Z",
    )


def _signal() -> eh.HookSignal:
    return eh.HookSignal(
        source="twitter", lane="account", text="Confirmed launch movement",
        author="newsdesk", ts="2026-06-27T00:01:00Z", engagement=42,
    )


def _verdict() -> eh.HookVerdict:
    entries = [
        eh.TimelineEntry(ts=f"2026-06-27T00:0{i}:00Z", text=text, source="twitter")
        for i, text in enumerate(("First", "Second", "Third", "Fourth"), start=1)
    ]
    return eh.HookVerdict(
        turning_score=91, numeric=92.0, materiality=90, status="escalating",
        decision="push", summary="Launch window moved.", new_entries=entries,
    )


class FakeAdapter:
    def __init__(self, content: str) -> None:
        self.content = content
        self.requests: list[Any] = []

    async def complete(self, request: Any) -> SimpleNamespace:
        self.requests.append(request)
        return SimpleNamespace(content=self.content)


class FakeFeishuClient:
    def __init__(self, app_id: str = "", app_secret: str = "") -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.calls: list[dict[str, Any]] = []

    async def send_message(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"code": 0}


class FakeResponse:
    def __init__(self, *, status_code: int = 200, body: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._body = body if body is not None else {"code": 0}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._body


class FakeAsyncClient:
    captured: dict[str, Any] = {}
    response: FakeResponse = FakeResponse()

    def __init__(self, *, timeout: float, trust_env: bool) -> None:
        self.captured.update({"timeout": timeout, "trust_env": trust_env})

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, json: dict[str, Any]) -> FakeResponse:
        self.captured.update({"url": url, "json": json})
        return self.response


async def test_twitter_search_maps_options_and_keeps_rate_limit_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_search(query: str, config: XClientConfig, options: Any) -> list[XPost]:
        captured.update({"query": query, "config": config, "options": options})
        return [_post()]

    monkeypatch.setattr(twitter_module, "search_x_posts", fake_search)
    search = make_twitter_search_fn(_x_config())
    assert await search(eh.TwitterQuery(query="from:news", max_results=7, days=3)) == [_post()]
    assert captured["query"] == "from:news"
    assert captured["options"].max_results == 7
    assert captured["options"].days == 3
    assert captured["options"].search_type == "Latest"

    partial = [_post("Partial")]

    async def rate_limited(query: str, config: XClientConfig, options: Any) -> list[XPost]:
        raise twitter_module.XRateLimitError(partial, retry_after_seconds=30)

    monkeypatch.setattr(twitter_module, "search_x_posts", rate_limited)
    assert await search(eh.TwitterQuery(query="launch")) == partial


async def test_assess_fn_parses_json_fences_clamps_and_raises_on_invalid() -> None:
    adapter = FakeAdapter(
        '{"materiality": 88, "summary": "已确认收尾", "developments": '
        '[{"text": "窗口已确认提前", "ts": "2026-06-27T00:01:00Z", "source": "twitter"}], "resolved": true}'
    )
    result = await make_assess_fn(adapter, "test-model")(
        eh.AssessRequest(hook=_hook(), signals=[_signal()], prev_summary="旧摘要", recent_developments=["已报告旧进展"])
    )
    assert (result.materiality, result.summary, result.status_hint) == (88, "已确认收尾", "resolved")
    assert result.developments == [eh.Development(text="窗口已确认提前", ts="2026-06-27T00:01:00Z", source="twitter")]
    assert adapter.requests[0].model == "test-model"
    assert adapter.requests[0].temperature == 0.2
    prompt = adapter.requests[0].messages[0].content
    assert all(text in prompt for text in ("Launch Watch", "旧摘要", "Confirmed launch movement", '"developments"', "已报告过的进展", "已报告旧进展", "必须 ISO8601"))

    fenced = FakeAdapter('```json\n{"materiality": 120, "summary": "仍在发酵", "developments": [], "resolved": false}\n```')
    result = await make_assess_fn(fenced, "test-model")(
        eh.AssessRequest(hook=_hook(), signals=[_signal()])
    )
    assert (result.materiality, result.summary, result.status_hint) == (100, "仍在发酵", None)
    assert result.developments == []
    with pytest.raises(runtime_module.HookRuntimeError):
        await make_assess_fn(FakeAdapter("not json"), "test-model")(
            eh.AssessRequest(hook=_hook(), signals=[])
        )


async def test_push_fn_feishu_webhook_and_missing_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeFeishuClient()
    await make_push_fn(feishu_client=client, chat_id="oc_123")(_hook(), _verdict())
    assert client.calls[0]["msg_type"] == "interactive"
    assert client.calls[0]["chat_id"] == "oc_123"
    assert "Launch Watch" in client.calls[0]["content"]

    FakeAsyncClient.captured = {}
    FakeAsyncClient.response = FakeResponse(status_code=200, body={"code": 0})
    monkeypatch.setattr(push_module.httpx, "AsyncClient", FakeAsyncClient)
    await make_push_fn(
        feishu_client=None, chat_id="", webhook_url="https://feishu.test/hook",
        webhook_secret="secret",
    )(_hook(), _verdict())
    body = FakeAsyncClient.captured["json"]
    assert FakeAsyncClient.captured["trust_env"] is False
    assert FakeAsyncClient.captured["url"] == "https://feishu.test/hook"
    assert body["msg_type"] == "interactive"
    assert body["card"]["header"]["title"]["content"].startswith("🔔")
    assert "timestamp" in body and "sign" in body
    await make_push_fn(feishu_client=None, chat_id="", webhook_url="")(_hook(), _verdict())


class ReplyFeishuClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    async def send_message(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.payload


async def test_push_fn_raises_when_feishu_client_returns_error_code() -> None:
    # 飞书 client 在机器人被移出群/chat_id 失效时返回 code!=0 而不抛错——push 必须把它变成失败。
    client = ReplyFeishuClient({"code": 19001, "msg": "bot removed"})
    with pytest.raises(runtime_module.HookRuntimeError) as exc_info:
        await make_push_fn(feishu_client=client, chat_id="oc_123")(_hook(), _verdict())
    assert "19001" in str(exc_info.value)
    assert client.calls  # 确认确实尝试投递过


async def test_push_fn_raises_when_webhook_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAsyncClient.captured = {}
    FakeAsyncClient.response = FakeResponse(status_code=500, body={"code": 0})
    monkeypatch.setattr(push_module.httpx, "AsyncClient", FakeAsyncClient)
    with pytest.raises(runtime_module.HookRuntimeError):
        await make_push_fn(
            feishu_client=None, chat_id="", webhook_url="https://feishu.test/hook",
        )(_hook(), _verdict())


async def test_push_fn_raises_when_webhook_body_code_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 飞书 webhook 常返回 HTTP 200 + body 里 code!=0（签名错/频控）。
    FakeAsyncClient.captured = {}
    FakeAsyncClient.response = FakeResponse(status_code=200, body={"code": 19001, "msg": "sign fail"})
    monkeypatch.setattr(push_module.httpx, "AsyncClient", FakeAsyncClient)
    with pytest.raises(runtime_module.HookRuntimeError) as exc_info:
        await make_push_fn(
            feishu_client=None, chat_id="", webhook_url="https://feishu.test/hook",
            webhook_secret="secret",
        )(_hook(), _verdict())
    assert "19001" in str(exc_info.value)


async def test_build_hook_runtime_wires_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    def fake_twitter(x_config: XClientConfig) -> str: captured["x_config"] = x_config; return "twitter"
    def fake_assess(adapter: Any, model: str) -> str: captured.update({"adapter": adapter, "model": model}); return "assess"
    def fake_push(**kwargs: Any) -> str: captured["push"] = kwargs; return "push"
    for name, value in {"make_twitter_search_fn": fake_twitter, "make_assess_fn": fake_assess, "make_push_fn": fake_push, "FeishuClient": FakeFeishuClient}.items():
        monkeypatch.setattr(runtime_module, name, value)
    for name, value in {"twitter_username": "", "twitter_email": "settings-email", "twitter_password": "settings-pass", "twitter_proxy_url": "", "twitter_cookies_file": "", "feishu_app_id": "app", "feishu_app_secret": "secret", "feishu_chat_id": "oc_123", "feishu_webhook_url": "https://hook", "feishu_webhook_secret": "hook-secret"}.items():
        monkeypatch.setattr(settings, name, value)
    for name, value in {"TWITTER_USERNAME": "env-user", "TWITTER_PROXY_URL": "http://proxy", "TWITTER_COOKIES_FILE": "env-cookies.json"}.items():
        monkeypatch.setenv(name, value)
    runtime = build_hook_runtime(object(), "model-a")
    assert isinstance(runtime, HookRuntime)
    assert (runtime.twitter_search_fn, runtime.assess_fn, runtime.push_fn) == ("twitter", "assess", "push")
    x_config = captured["x_config"]
    assert (x_config.username, x_config.email, x_config.password) == ("env-user", "settings-email", "settings-pass")
    assert (x_config.proxy_url, x_config.cookies_file) == ("http://proxy", "env-cookies.json")
    assert captured["push"]["feishu_client"].app_id == "app"
    assert captured["push"]["chat_id"] == "oc_123"
