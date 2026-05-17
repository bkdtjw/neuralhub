from __future__ import annotations


PROVIDER_REJECTION_MARKERS = (
    "high risk",
    "不安全",
    "敏感内容",
    "sensitive content",
    "rejected because it was considered",
)


def is_provider_rejection(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker.lower() in text for marker in PROVIDER_REJECTION_MARKERS)


def provider_rejection_content(exc: Exception) -> str:
    detail = str(exc).strip()
    return (
        "模型服务拒绝分析当前页面内容，通常是新闻、政治人物图片或网页内容触发了"
        f"供应商安全策略。浏览器本身未崩溃。原始错误：{detail}"
    )


__all__ = ["is_provider_rejection", "provider_rejection_content"]
