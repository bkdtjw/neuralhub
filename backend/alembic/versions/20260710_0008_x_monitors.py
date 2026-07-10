from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260710_0008"
down_revision = "20260708_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    # 幂等守卫：AUTO_CREATE_TABLES=true 的环境可能已由 create_all 建过表。
    if "x_monitors" not in tables:
        op.create_table(
            "x_monitors",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("query", sa.String(length=200), nullable=False),
            sa.Column("interval_minutes", sa.Integer(), nullable=False),
            sa.Column("days_window", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("search_type", sa.String(length=10), nullable=False, server_default="Latest"),
            sa.Column("threshold_likes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("threshold_views", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_run_at", sa.DateTime(), nullable=True),
            sa.Column("last_status", sa.String(length=20), nullable=False, server_default=""),
        )
    if "x_monitor_hits" not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            "x_monitor_hits",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column(
                "monitor_id",
                sa.String(length=64),
                sa.ForeignKey("x_monitors.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("tweet_url", sa.String(length=500), nullable=False),
            sa.Column("author_handle", sa.String(length=100), nullable=False, server_default=""),
            sa.Column("text_snippet", sa.String(length=500), nullable=False, server_default=""),
            sa.Column("likes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("hit_reason", sa.String(length=100), nullable=False, server_default=""),
            sa.Column("notified", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("monitor_id", "tweet_url", name="uq_x_monitor_hit"),
        )


def downgrade() -> None:
    # 纯新增的特性表，回退即删；先删子表（FK 依赖）。
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "x_monitor_hits" in tables:
        op.drop_table("x_monitor_hits")
    if "x_monitors" in tables:
        op.drop_table("x_monitors")
