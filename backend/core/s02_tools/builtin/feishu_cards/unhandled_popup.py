from __future__ import annotations

from .models import ButtonSpec, CardAction, button, card


def build_unhandled_popup_card(
    url: str,
    screenshot_key: str,
    tried_selectors: list[str],
) -> dict:
    selector_text = "\n".join(f"- `{selector}`" for selector in tried_selectors) or "- none"
    elements: list[dict] = [
        {
            "tag": "markdown",
            "content": f"Unhandled popup at {url}\nTried selectors:\n{selector_text}",
        }
    ]
    if screenshot_key:
        elements.append(
            {
                "tag": "img",
                "img_key": screenshot_key,
                "alt": {"tag": "plain_text", "content": "screenshot"},
            }
        )
    elements.append(
        {
            "tag": "action",
            "actions": [
                button(
                    ButtonSpec(
                        text="Provide selector",
                        button_type="primary",
                        action=CardAction(
                            action_type=f"provide_selector:{url}",
                            payload={"url": url},
                        ),
                    )
                )
            ],
        }
    )
    return card("Unhandled Popup", elements, template="red")


__all__ = ["build_unhandled_popup_card"]
