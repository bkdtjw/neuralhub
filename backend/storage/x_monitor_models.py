from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class XMonitorRecord(Base):
    __tablename__ = "x_monitors"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    query: Mapped[str] = mapped_column(String(200), nullable=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    days_window: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    search_type: Mapped[str] = mapped_column(String(10), default="Latest", nullable=False)
    threshold_likes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    threshold_views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(20), default="", nullable=False)


class XMonitorHitRecord(Base):
    __tablename__ = "x_monitor_hits"
    # 同一监控对同一条推文只记一次命中（也保证只告警一次）。
    __table_args__ = (UniqueConstraint("monitor_id", "tweet_url", name="uq_x_monitor_hit"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    monitor_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("x_monitors.id", ondelete="CASCADE"), nullable=False
    )
    tweet_url: Mapped[str] = mapped_column(String(500), nullable=False)
    author_handle: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    text_snippet: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    likes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hit_reason: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    notified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class XMonitor(BaseModel):
    id: str
    query: str
    interval_minutes: int
    days_window: int
    search_type: str
    threshold_likes: int
    threshold_views: int
    enabled: bool
    created_at: datetime
    last_run_at: datetime | None
    last_status: str


class XMonitorHit(BaseModel):
    id: str
    monitor_id: str
    tweet_url: str
    author_handle: str
    text_snippet: str
    likes: int
    views: int
    hit_reason: str
    notified: bool
    created_at: datetime


__all__ = ["XMonitor", "XMonitorHit", "XMonitorHitRecord", "XMonitorRecord"]
