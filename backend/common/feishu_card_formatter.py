"""LLM-based card formatter — converts agent reply into card variable JSON.

Pure Python + asyncio. Depends on LLMAdapter (injected), not on httpx or FastAPI.
"""

from __future__ import annotations

from typing import Any

from backend.adapters.base import LLMAdapter
from backend.common.feishu_card import (
    CardRegistry,
    build_formatter_prompt,
)
from backend.common.feishu_card_formatter_support import (
    build_fallback_variables,
    build_retry_prompt,
    clean_llm_json,
    compact_preview,
    parse_variables,
)
from backend.common.logging import get_logger
from backend.common.types import LLMRequest, Message

logger = get_logger(component="feishu_card_formatter")


class CardFormatter:
    """Uses an LLM to reformat an agent reply into card template variables."""

    def __init__(self, adapter: LLMAdapter, model: str) -> None:
        self._adapter = adapter
        self._model = model

    async def format(
        self,
        scenario: str,
        agent_reply: str,
        tool_name: str,
        tool_arguments: dict[str, Any],
        registry: CardRegistry | None = None,
        existing_variables: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Call the LLM to produce card variable JSON for variables not yet filled.

        Args:
            existing_variables: Variables already collected by executor code
                (e.g. task_name, status_text, started_at). These will be excluded
                from LLM extraction — only missing variables are sent to the LLM.
        """
        reg = registry or CardRegistry()
        cfg = reg.get_scenario(scenario)
        if cfg is None:
            return {}

        existing = existing_variables or {}
        # Only ask LLM to extract variables not already provided
        missing_vars = {k: v for k, v in cfg.variables.items() if k not in existing}

        # Nothing for LLM to extract — skip the call entirely
        if not missing_vars:
            return {}

        prompt = build_formatter_prompt(
            scenario,
            agent_reply,
            tool_name,
            tool_arguments,
            variables_to_extract=missing_vars,
            registry=reg,
        )

        try:
            request = LLMRequest(
                model=self._model,
                messages=[Message(role="user", content=prompt)],
                temperature=0.2,
                max_tokens=2000,
            )
            response = await self._adapter.complete(request)
            variables = parse_variables(response.content)
            return _fill_missing_variables(variables, missing_vars, agent_reply)

        except Exception as first_error:
            raw = getattr(locals().get("response", None), "content", "")
            logger.warning(
                "feishu_card_format_retry",
                scenario=scenario,
                model=self._model,
                error=str(first_error),
                raw_preview=compact_preview(str(raw)),
            )
            try:
                retry_prompt = build_retry_prompt(prompt, str(raw), str(first_error))
                retry_request = LLMRequest(
                    model=self._model,
                    messages=[Message(role="user", content=retry_prompt)],
                    temperature=0.0,
                    max_tokens=2000,
                )
                retry_response = await self._adapter.complete(retry_request)
                variables = parse_variables(retry_response.content)
                return _fill_missing_variables(variables, missing_vars, agent_reply)
            except Exception as retry_error:
                retry_raw = getattr(locals().get("retry_response", None), "content", "")
                logger.warning(
                    "feishu_card_format_fallback",
                    scenario=scenario,
                    model=self._model,
                    first_error=str(first_error),
                    retry_error=str(retry_error),
                    raw_preview=compact_preview(str(retry_raw)),
                )
                return _build_fallback(missing_vars, agent_reply)


def _clean_llm_json(raw: str) -> str:
    """Strip markdown fences and noise from LLM JSON output."""
    return clean_llm_json(raw)


def _build_fallback(
    missing_vars: dict[str, Any],
    agent_reply: str,
) -> dict[str, str]:
    """Generate fallback values when LLM formatting fails."""
    return build_fallback_variables(missing_vars, agent_reply)


def _fill_missing_variables(
    variables: dict[str, str],
    missing_vars: dict[str, Any],
    agent_reply: str,
) -> dict[str, str]:
    fallback = _build_fallback(missing_vars, agent_reply)
    for key in missing_vars:
        if not variables.get(key):
            variables[key] = fallback.get(key, "")
    return variables


__all__ = ["CardFormatter"]
