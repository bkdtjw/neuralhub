from __future__ import annotations

import base64
import hashlib
import hmac
import json

from backend.common.errors import AgentError
from backend.common.logging import get_logger

logger = get_logger(component="feishu_signature")


def verify_signature(
    body: bytes,
    timestamp: str,
    nonce: str,
    signature: str,
    verification_token: str = "",
    encrypt_key: str = "",
) -> bool:
    """按飞书真实协议校验回调请求——以本端配置决定校验方式，而非请求头。

    真机抓包实证（2026-07-13）：飞书**永远**发 ``X-Lark-Signature`` 头，公式统一为
    sha256(timestamp + nonce + encrypt_key + body)；未配置 Encrypt Key 时
    encrypt_key 按空串参与计算——即该签名无密钥、任何人可伪造，不具备鉴权价值。
    因此：
    - 配了 Encrypt Key：必须带签名头且签名匹配（此时密钥非空，签名可信）。
    - 只配 Verification Token（明文模式）：比对 body 内 token 字段
      （v2 事件在 header.token，v1/卡片回调在顶层 token），忽略无密钥签名头。
    - 两者都未配置：放行（dev 默认）。
    """
    try:
        if encrypt_key:
            if not signature:
                return False
            expected = hashlib.sha256(
                f"{timestamp}{nonce}{encrypt_key}".encode("utf-8") + body
            ).hexdigest()
            return hmac.compare_digest(expected, signature)
        if verification_token:
            return _body_token_matches(body, verification_token)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("feishu_signature_verify_failed", error=str(exc))
        raise AgentError("FEISHU_SIGNATURE_VERIFY_ERROR", str(exc)) from exc


def _body_token_matches(body: bytes, verification_token: str) -> bool:
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    token = ""
    header = data.get("header")
    if isinstance(header, dict):
        token = str(header.get("token") or "")
    if not token:
        token = str(data.get("token") or "")
    return bool(token) and hmac.compare_digest(token, verification_token)


def decrypt_payload(encrypt: str, encrypt_key: str) -> dict:
    try:
        if not encrypt_key:
            raise AgentError("FEISHU_ENCRYPT_KEY_MISSING", "feishu_encrypt_key is required")
        try:
            from Crypto.Cipher import AES
        except ImportError as exc:
            raise AgentError("PYCRYPTODOME_MISSING", "pycryptodome is required") from exc

        key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()
        cipher = AES.new(key, AES.MODE_CBC, key[:16])
        decrypted = cipher.decrypt(base64.b64decode(encrypt))
        payload = _unpad(decrypted).decode("utf-8")
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise AgentError("FEISHU_DECRYPT_INVALID_JSON", "decrypted payload is not an object")
        return data
    except AgentError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("feishu_payload_decrypt_failed", error=str(exc))
        raise AgentError("FEISHU_PAYLOAD_DECRYPT_ERROR", str(exc)) from exc


def _unpad(value: bytes) -> bytes:
    pad = value[-1]
    if pad < 1 or pad > 16:
        raise AgentError("FEISHU_AES_PADDING_ERROR", "invalid AES padding")
    return value[:-pad]


__all__ = ["decrypt_payload", "verify_signature"]
