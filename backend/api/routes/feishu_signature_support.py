"""Shared Feishu callback signature verification for route modules.

Reads the real Lark request headers and delegates to
``backend.common.feishu_signature.verify_signature`` so the main event route and
the card action route share the same (correct) verification as ``feishu_events``.
"""

from __future__ import annotations

from fastapi import Request

from backend.common.errors import AgentError
from backend.common.feishu_signature import verify_signature
from backend.common.logging import get_logger
from backend.config.settings import settings

logger = get_logger(component="feishu_signature_support")


def request_signature_ok(request: Request, body: bytes) -> bool:
    """Return True when the callback passes Feishu's official verification.

    Reads the real Lark headers ``X-Lark-Request-Timestamp`` /
    ``X-Lark-Request-Nonce`` / ``X-Lark-Signature``. 加密模式（配了
    ``feishu_encrypt_key``）按签名头校验；明文模式（只配
    ``feishu_verification_token``）飞书不发签名头，改为比对 body 内的 token
    字段；两者都未配置（dev 默认）放行。校验不过或内部错误返回 False，
    由调用方拒绝请求。
    """
    timestamp = request.headers.get("X-Lark-Request-Timestamp", "")
    nonce = request.headers.get("X-Lark-Request-Nonce", "")
    signature = request.headers.get("X-Lark-Signature", "")
    try:
        return verify_signature(
            body,
            timestamp,
            nonce,
            signature,
            str(getattr(settings, "feishu_verification_token", "") or ""),
            str(getattr(settings, "feishu_encrypt_key", "") or ""),
        )
    except AgentError:
        logger.warning("feishu_signature_verify_error")
        return False


__all__ = ["request_signature_ok"]
