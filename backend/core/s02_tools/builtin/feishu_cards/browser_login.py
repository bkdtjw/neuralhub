from __future__ import annotations


def build_sms_phone_card(site: str, session_id: str, reason: str = "") -> dict:
    return _card(
        f"{site} 登录",
        [
            _markdown(
                f"检测到 **{site}** 需要登录。优先使用短信登录。"
                + (f"\n\n当前状态：{reason}" if reason else "")
            ),
            _form(
                "browser_login_sms_phone",
                [
                    _input("phone", "请输入手机号", "telephone", required=True, max_length=20),
                    _submit_button(
                        "发送验证码",
                        "browser_login_sms_request",
                        session_id,
                        button_type="primary_filled",
                    ),
                ],
            ),
            _actions(
                [
                    _callback_button("改用密码登录", "browser_login_password_open", session_id),
                    _callback_button("取消", "browser_login_cancel", session_id, "danger"),
                ]
            ),
        ],
    )


def build_sms_code_card(site: str, session_id: str, phone_hint: str = "") -> dict:
    return _card(
        f"{site} 验证码",
        [
            _markdown(f"验证码已发送{phone_hint}，请填写短信验证码。"),
            _form(
                "browser_login_sms_code",
                [
                    _input("code", "请输入短信验证码", "number", required=True, max_length=10),
                    _submit_button(
                        "提交验证码",
                        "browser_login_sms_submit",
                        session_id,
                        button_type="primary_filled",
                    ),
                ],
            ),
            _actions(
                [
                    _callback_button("改用密码登录", "browser_login_password_open", session_id),
                    _callback_button("取消", "browser_login_cancel", session_id, "danger"),
                ]
            ),
        ],
    )


def build_password_card(site: str, session_id: str) -> dict:
    return _card(
        f"{site} 密码登录",
        [
            _markdown("请填写账号和密码。密码只用于当前浏览器会话，不会保存。"),
            _form(
                "browser_login_password",
                [
                    _input("account", "手机号 / 用户名", "text", required=True, max_length=80),
                    _input("password", "密码", "password", required=True, max_length=128),
                    _submit_button(
                        "提交密码登录",
                        "browser_login_password_submit",
                        session_id,
                        button_type="primary_filled",
                    ),
                ],
            ),
            _actions(
                [
                    _callback_button("改用短信登录", "browser_login_sms_open", session_id),
                    _callback_button("取消", "browser_login_cancel", session_id, "danger"),
                ]
            ),
        ],
        template="orange",
    )


def _card(title: str, elements: list[dict], template: str = "orange") -> dict:
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "fill"},
        "header": {
            "template": template,
            "title": {"tag": "plain_text", "content": title},
        },
        "body": {"elements": elements},
    }


def _markdown(content: str) -> dict:
    return {"tag": "markdown", "content": content}


def _form(name: str, elements: list[dict]) -> dict:
    return {"tag": "form", "name": name, "elements": elements}


def _input(
    name: str,
    placeholder: str,
    input_type: str,
    required: bool = False,
    max_length: int = 80,
) -> dict:
    return {
        "tag": "input",
        "name": name,
        "placeholder": {"tag": "plain_text", "content": placeholder},
        "required": required,
        "max_length": max_length,
        "input_type": input_type,
        "width": "fill",
    }


def _submit_button(
    text: str,
    action_type: str,
    session_id: str,
    button_type: str = "primary",
) -> dict:
    return {
        "tag": "button",
        "name": action_type,
        "text": {"tag": "plain_text", "content": text},
        "type": button_type,
        "form_action_type": "submit",
        "behaviors": [{"type": "callback", "value": _value(action_type, session_id)}],
    }


def _actions(actions: list[dict]) -> dict:
    return {
        "tag": "column_set",
        "horizontal_spacing": "8px",
        "columns": [
            {"tag": "column", "width": "auto", "elements": [action]} for action in actions
        ],
    }


def _callback_button(
    text: str,
    action_type: str,
    session_id: str,
    button_type: str = "default",
) -> dict:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": text},
        "type": button_type,
        "value": _value(action_type, session_id),
        "behaviors": [{"type": "callback", "value": _value(action_type, session_id)}],
    }


def _value(action_type: str, session_id: str) -> dict[str, str]:
    return {"action_type": action_type, "action": action_type, "session_id": session_id}


__all__ = ["build_password_card", "build_sms_code_card", "build_sms_phone_card"]
