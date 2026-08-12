"""add user bio and legacy llm usage table

Revision ID: 007_user_bio_llm_usage
Revises: 006_user_is_active
Create Date: 2026-08-03

补齐本地联调暴露的两处历史 schema 缺口：
1. users.bio：设置页个人简介字段使用该列，旧 SQLite 库可能缺失。
2. llm_usage：CostTracker 仍写入该兼容表，用于本地和管理端用量汇总。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007_user_bio_llm_usage"
down_revision: str | None = "006_user_is_active"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" in tables:
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "bio" not in user_columns:
            op.add_column("users", sa.Column("bio", sa.Text(), nullable=True))

    if "llm_usage" not in tables:
        op.create_table(
            "llm_usage",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("model_name", sa.String(100), nullable=False),
            sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cost", sa.Float(), nullable=False, server_default="0"),
            sa.Column("request_id", sa.String(100), nullable=True),
            sa.Column("agent_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_llm_usage_id", "llm_usage", ["id"])
        op.create_index("ix_llm_usage_model_name", "llm_usage", ["model_name"])
        op.create_index("ix_llm_usage_request_id", "llm_usage", ["request_id"])
        op.create_index("ix_llm_usage_agent_id", "llm_usage", ["agent_id"])
        op.create_index("ix_llm_usage_created_at", "llm_usage", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "llm_usage" in tables:
        op.drop_index("ix_llm_usage_created_at", table_name="llm_usage")
        op.drop_index("ix_llm_usage_agent_id", table_name="llm_usage")
        op.drop_index("ix_llm_usage_request_id", table_name="llm_usage")
        op.drop_index("ix_llm_usage_model_name", table_name="llm_usage")
        op.drop_index("ix_llm_usage_id", table_name="llm_usage")
        op.drop_table("llm_usage")

    if "users" in tables:
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "bio" in user_columns:
            op.drop_column("users", "bio")
