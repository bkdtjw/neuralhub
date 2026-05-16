from __future__ import annotations

from backend.core.s01_agent_loop.tool_review import _parse_review_results


def test_parse_review_results_accepts_fenced_aliases() -> None:
    results = _parse_review_results(
        """```json
        [
          {
            "decision": "approve",
            "reason": "读取 README.md 与当前步骤一致",
            "risk_level": "none"
          }
        ]
        ```""",
        1,
    )

    assert results[0].decision == "auto_approve"
    assert results[0].risk_level == "low"


def test_parse_review_results_accepts_embedded_object_aliases() -> None:
    results = _parse_review_results(
        '审核结果：{"decision":"reject","reason":"目标范围不一致","risk_level":"moderate"}',
        1,
    )

    assert results[0].decision == "auto_reject"
    assert results[0].risk_level == "medium"
