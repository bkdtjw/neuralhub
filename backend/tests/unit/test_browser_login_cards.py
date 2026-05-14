from __future__ import annotations

from backend.core.s02_tools.builtin.feishu_cards import (
    build_password_card,
    build_sms_code_card,
    build_sms_phone_card,
)


def test_sms_phone_card_has_form_and_password_fallback() -> None:
    card = build_sms_phone_card("京东", "sid")

    elements = card["body"]["elements"]
    form = next(item for item in elements if item["tag"] == "form")
    assert form["elements"][0]["name"] == "phone"
    assert form["elements"][0]["input_type"] == "telephone"
    assert form["elements"][1]["behaviors"][0]["value"]["action_type"] == (
        "browser_login_sms_request"
    )
    assert "browser_login_password_open" in str(card)


def test_sms_code_and_password_cards_use_fixed_actions() -> None:
    code_card = build_sms_code_card("京东", "sid")
    password_card = build_password_card("京东", "sid")

    assert "browser_login_sms_submit" in str(code_card)
    assert "browser_login_password_submit" in str(password_card)
    assert "password" in str(password_card)
