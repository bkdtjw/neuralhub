from __future__ import annotations

from backend.core.s02_tools.builtin.browser_agent.models import (
    ActionKind,
    BrowserAction,
    ElementHint,
    VisionObservation,
)


def test_browser_action_round_trip_json() -> None:
    action = BrowserAction(
        kind=ActionKind.CLICK_COORDS,
        x=42,
        y=84,
        reason="target visible",
    )

    loaded = BrowserAction.model_validate_json(action.model_dump_json())

    assert loaded == action
    assert loaded.kind == ActionKind.CLICK_COORDS


def test_browser_action_ignores_extra_fields() -> None:
    action = BrowserAction.model_validate(
        {
            "kind": "click_selector",
            "selector": ".btn",
            "thinking": "I should click this",
            "extra": "stuff",
        }
    )

    assert action.kind == ActionKind.CLICK_SELECTOR
    assert action.selector == ".btn"
    assert "thinking" not in action.model_dump()


def test_vision_observation_round_trip_json() -> None:
    observation = VisionObservation(
        page_summary="Search page",
        visible_elements=[
            ElementHint(
                description="Search input",
                selector_hint="input[name=q]",
                bbox=(1, 2, 3, 4),
                confidence=0.9,
            )
        ],
        target_element=ElementHint(description="Submit button", confidence=0.7),
        suggested_next_action="Fill the search box",
        screenshot_importance=0.8,
        task_relevance=0.4,
        screenshot_reason="login required",
        confidence=0.8,
        raw_text="raw",
    )

    loaded = VisionObservation.model_validate_json(observation.model_dump_json())

    assert loaded == observation
    assert loaded.visible_elements[0].bbox == (1, 2, 3, 4)
    assert loaded.screenshot_importance == 0.8
    assert loaded.task_relevance == 0.4
    assert loaded.screenshot_reason == "login required"
