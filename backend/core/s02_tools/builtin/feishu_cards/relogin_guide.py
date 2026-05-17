from __future__ import annotations

from .models import ButtonSpec, CardAction, button, card


def build_relogin_card(site: str, step_index: int, total: int) -> dict:
    action_type = f"relogin_done:{site}"
    elements = [
        {
            "tag": "markdown",
            "content": f"Relogin required for **{site}**.\nStep {step_index} of {total}.",
        },
        {
            "tag": "action",
            "actions": [
                button(
                    ButtonSpec(
                        text="Done",
                        button_type="primary",
                        action=CardAction(action_type=action_type, payload={"site": site}),
                    )
                ),
                button(
                    ButtonSpec(
                        text="Skip",
                        action=CardAction(action_type=f"skip_site:{site}", payload={"site": site}),
                    )
                ),
            ],
        },
    ]
    return card("Relogin Guide", elements, template="orange")


__all__ = ["build_relogin_card"]
