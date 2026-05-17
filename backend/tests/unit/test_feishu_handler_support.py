from __future__ import annotations

from backend.api.routes.feishu_handler_support import (
    is_provider_rejection_error,
    resolve_error_reply,
)
from backend.common.errors import LLMError


def test_resolve_error_reply_explains_provider_rejection() -> None:
    reply = resolve_error_reply(
        LLMError("API_ERROR", "The request was rejected because it was considered high risk", "p")
    )

    assert "模型服务拒绝" in reply
    assert "飞书通道本身没有崩溃" in reply
    assert is_provider_rejection_error(
        LLMError("API_ERROR", "The request was rejected because it was considered high risk", "p")
    )


def test_resolve_error_reply_keeps_generic_message_for_other_errors() -> None:
    assert "处理消息时出错" in resolve_error_reply(RuntimeError("boom"))
