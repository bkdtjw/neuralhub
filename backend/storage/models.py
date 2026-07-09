from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SessionRecord(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    workspace: Mapped[str] = mapped_column(Text, default="", nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="idle", nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=10000, nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    messages: Mapped[list[MessageRecord]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class MessageRecord(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), default="user_request", nullable=False)
    ephemeral: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tool_calls_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_results_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    session: Mapped[SessionRecord] = relationship(back_populates="messages")


class ProviderRecord(Base):
    __tablename__ = "providers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(20), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # TODO: Encrypt provider API keys at rest instead of storing plaintext secrets.
    api_key: Mapped[str] = mapped_column(Text, default="", nullable=False)
    default_model: Mapped[str] = mapped_column(String(100), nullable=False)
    available_models_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    extra_headers_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    enable_prompt_cache: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    prompt_cache_retention: Mapped[str | None] = mapped_column(String(20), nullable=True)
    extra_body_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    roles: Mapped[str] = mapped_column(String(200), default="", nullable=False)


class MCPServerRecord(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    transport: Mapped[str] = mapped_column(String(10), nullable=False)
    command: Mapped[str] = mapped_column(Text, default="", nullable=False)
    args_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    env_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SubAgentTaskRecord(Base):
    __tablename__ = "sub_agent_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    parent_task_id: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    input_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    worker_id: Mapped[str] = mapped_column(String(100), default="", nullable=False, index=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    started_at: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    timeout_seconds: Mapped[float] = mapped_column(Float, default=60.0, nullable=False)
    lease_expires_at: Mapped[float] = mapped_column(Float, default=0.0, nullable=False, index=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class ScheduledTaskRecord(Base):
    __tablename__ = "scheduled_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    cron: Mapped[str] = mapped_column(String(100), default="0 * * * *", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai", nullable=False)
    prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    spec_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    notify_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    output_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    card_scenario: Mapped[str | None] = mapped_column(String(100), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # TODO: Migrate to datetime.now(UTC) + TIMESTAMP WITH TIME ZONE.
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_status: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    last_run_output: Mapped[str] = mapped_column(Text, default="", nullable=False)


class HookRecord(Base):
    __tablename__ = "event_hooks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hook_json: Mapped[str] = mapped_column(Text, nullable=False)
    state_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class RunTraceRecord(Base):
    __tablename__ = "run_traces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(100), default="", nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(50), default="", nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_code: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class LoginWorkflowRecord(Base):
    __tablename__ = "login_workflows"

    user_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    site_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    status: Mapped[str] = mapped_column(String(30), default="EXPIRED", nullable=False, index=True)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_fresh_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    workflow_id: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    current_step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_steps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


try:
    from backend.core.s13_knowledge import db_models as _knowledge_db_models  # noqa: F401
except ImportError:
    _knowledge_db_models = None


__all__ = [
    "Base",
    "HookRecord",
    "MCPServerRecord",
    "MessageRecord",
    "ProviderRecord",
    "LoginWorkflowRecord",
    "RunTraceRecord",
    "ScheduledTaskRecord",
    "SessionRecord",
    "SubAgentTaskRecord",
]
