"""add is_active column to users table

Revision ID: 006_user_is_active
Revises: 005_platform_tokens
Create Date: 2026-07-01

修复 users 表 schema 不一致：
- ORM 与部分原生 SQL 查询使用 is_active（True=启用）语义，但 users 表历史只存
  disabled（True=禁用），导致 `SELECT is_active FROM users` 报
  sqlite3.OperationalError: no such column: is_active。
- 本迁移新增 is_active 列（NOT NULL，默认 True），并用 `NOT disabled` 回填历史行，
  保证 is_active 与 disabled 互为逻辑反（is_active = NOT disabled），语义一致。
- 同时在 ORM（app/database/models.py 的 User 类）中补齐 is_active 字段，使
  init_database() 的 create_all 对全新数据库能直接创建该列。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006_user_is_active"
down_revision: str | None = "005_platform_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite 与 PostgreSQL 的布尔字面量不同：SQLite 用 0/1 整数，PG 用 true/false。
    # ADD COLUMN 要求 NOT NULL 列必须带 DEFAULT，故按方言选择默认值字面量。
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    true_literal = sa.text("1") if is_sqlite else sa.text("true")

    # 新增 is_active 列：先以默认 True 建列满足 NOT NULL 约束，
    # 随后用 NOT disabled 回填，确保历史数据语义正确（disabled=0 -> is_active=1）。
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=true_literal),
    )
    # NOT disabled 在 SQLite（整数取反）与 PostgreSQL（布尔取反）下均合法
    op.execute("UPDATE users SET is_active = NOT disabled")
    op.create_index("ix_users_is_active", "users", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_users_is_active", table_name="users")
    op.drop_column("users", "is_active")
