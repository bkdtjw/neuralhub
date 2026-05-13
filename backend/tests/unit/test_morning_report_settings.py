from __future__ import annotations

from backend.config.settings import Settings


def test_morning_report_user_ids_env_parses_csv(monkeypatch) -> None:
    monkeypatch.setenv("MORNING_REPORT_USER_IDS", "a, b,c,,")
    config = Settings()
    assert config.morning_report_user_ids == ["a", "b", "c"]
