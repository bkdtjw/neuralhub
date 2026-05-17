from __future__ import annotations

from backend.core.s02_tools.builtin.feishu_cards import (
    build_health_check_card,
    build_relogin_card,
    build_unhandled_popup_card,
)


def test_health_check_card_has_relogin_action() -> None:
    card = build_health_check_card([{"site": "example", "ok": False, "detail": "login"}])
    action = card["elements"][1]["actions"][0]
    assert action["value"]["action_type"] == "relogin_start"


def test_relogin_card_uses_site_action_prefix() -> None:
    card = build_relogin_card("hn", 1, 2)
    action = card["elements"][1]["actions"][0]
    assert action["value"]["action_type"] == "relogin_done:hn"
    assert action["value"]["site"] == "hn"


def test_unhandled_popup_card_includes_screenshot_and_selector_action() -> None:
    card = build_unhandled_popup_card("https://example.com/a", "img_key", [".close"])
    assert card["elements"][1]["img_key"] == "img_key"
    action = card["elements"][2]["actions"][0]
    assert action["value"]["action_type"] == "provide_selector:https://example.com/a"
