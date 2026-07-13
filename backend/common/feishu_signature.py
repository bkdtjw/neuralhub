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
    """按飞书官方协议校验回调请求。

    - 加密模式（开放平台配置了 Encrypt Key）：请求带 ``X-Lark-Signature`` 头，
      校验 sha256(timestamp + nonce + encrypt_key + body)。
    - 明文模式（只配 Verification Token）：飞书不发签名头，官方校验方式是
      比对 body 内的 token 字段（v2 事件在 header.token，v1/卡片回调在顶层 token）。
    - 两者都未配置：放行（dev 默认）。
    """
    try:
        if not signature:
            if not verification_token and not encrypt_key:
                return True
            if encrypt_key:
                # 配了 Encrypt Key 即加密模式，飞书必带签名头；无头视为伪造。
                return False
            return _body_token_matches(body, verification_token)
        if not encrypt_key:
            return False
        expected = hashlib.sha256(
            f"{timestamp}{nonce}{encrypt_key}".encode("utf-8") + body
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
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
