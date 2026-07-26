from __future__ import annotations

from backend.common import LLMError
from backend.common.types import ProviderConfig, ProviderType

from .anthropic_adapter import AnthropicAdapter
from .base import LLMAdapter
from .claude_code_adapter import ClaudeCodeAdapter
from .ollama_adapter import OllamaAdapter
from .openai_adapter import OpenAICompatAdapter


class AdapterFactory:
    @staticmethod
    def create(config: ProviderConfig) -> LLMAdapter:
        match config.provider_type:
            case ProviderType.ANTHROPIC:
                return AnthropicAdapter(config)
            case ProviderType.OPENAI_COMPAT:
                return OpenAICompatAdapter(config)
            case ProviderType.OLLAMA:
                return OllamaAdapter(config)
            case ProviderType.CLAUDE_CODE:
                return ClaudeCodeAdapter(config)
            case _:
                raise LLMError(
                    "UNSUPPORTED_PROVIDER",
                    f"Unsupported provider type: {config.provider_type}",
                    provider=str(config.provider_type),
                )


__all__ = ["AdapterFactory"]
