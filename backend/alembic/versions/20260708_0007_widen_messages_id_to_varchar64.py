from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260708_0007"
down_revision = "20260601_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "messages" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("messages")}
    if "id" not in columns:
        return
    # varchar(12) -> varchar(64)：Postgres 仅改元数据、不重写表；旧 12 位 id 在 (64) 下仍合法。
    op.alter_column(
        "messages",
        "id",
        type_=sa.String(length=64),
        existing_type=sa.String(length=12),
        existing_nullable=False,
    )


def downgrade() -> None:
    # 保守 no-op：回退到 varchar(12) 会截断已写入的 32 位 uuid4 主键，导致主键碰撞/数据损坏。
    # varchar(64) 对旧 12 位 id 完全向后兼容，无需回退列宽。
    return
