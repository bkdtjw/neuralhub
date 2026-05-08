from __future__ import annotations

from pathlib import Path

from backend.config.settings import settings as app_settings
from backend.core.s07_task_system.executor_support import build_report_url


def test_build_report_url_uses_configured_base(monkeypatch) -> None:
    monkeypatch.setattr(app_settings, "server_base_url", "http://example.com:8443")

    url = build_report_url(Path("/tmp/report.md"))

    assert url == "http://example.com:8443/reports/scheduled_tasks/report.md"


def test_build_report_url_defaults_to_public_8443(monkeypatch) -> None:
    monkeypatch.setattr(app_settings, "server_base_url", "")

    url = build_report_url(Path("/tmp/report.md"))

    assert url == "http://43.111.233.129:8443/reports/scheduled_tasks/report.md"


def test_build_report_url_encodes_chinese_filename(monkeypatch) -> None:
    monkeypatch.setattr(app_settings, "server_base_url", "http://example.com:8443")

    url = build_report_url(Path("/tmp/task_interview_daily-每日面试训练.md"))

    assert (
        url == "http://example.com:8443/reports/scheduled_tasks/"
        "task_interview_daily-%E6%AF%8F%E6%97%A5%E9%9D%A2%E8%AF%95%E8%AE%AD%E7%BB%83.md"
    )
