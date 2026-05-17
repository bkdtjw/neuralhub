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
    try:
        if not signature:
            return not verification_token and not encrypt_key
        candidates: list[str] = []
        if verification_token:
            candidates.append(
                hmac.new(
                    f"{timestamp}\n{verification_token}".encode("utf-8"),
                    body,
                    digestmod=hashlib.sha256,
                ).hexdigest()
            )
        if encrypt_key:
            candidates.append(
                hashlib.sha256(
                    f"{timestamp}{nonce}{encrypt_key}".encode("utf-8") + body
                ).hexdigest()
            )
        return any(hmac.compare_digest(item, signature) for item in candidates)
    except Exception as exc:  # noqa: BLE001
        logger.error("feishu_signature_verify_failed", error=str(exc))
        raise AgentError("FEISHU_SIGNATURE_VERIFY_ERROR", str(exc)) from exc


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
