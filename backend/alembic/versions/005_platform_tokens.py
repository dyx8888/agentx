"""add platform_tokens table for OAuth token storage

Revision ID: 005_platform_tokens
Revises: 004_p4_cost_audit
Create Date: 2026-07-01

新增 platform_tokens 表 — 存储各公司通过 OAuth 授权获取的平台访问令牌：
- access_token / refresh_token 使用 EncryptedText 加密落盘
- expires_at 建索引，供 Celery 定时刷新任务高效扫描即将过期的 token
- 每公司每平台唯一约束（company_id + platform），保证 token 记录不重复
- 与 Company.platform_credentials (EncryptedText JSON) 互补：
  credentials JSON 存全量凭证（含 app_key/app_secret）供适配器初始化，
  platform_tokens 表存 OAuth token 供定时刷新调度器高效查询。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005_platform_tokens"
down_revision: str | None = "004_p4_cost_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ============================================
    # platform_tokens — 平台 OAuth Token 表
    # access_token / refresh_token 在应用层通过 EncryptedText TypeDecorator 加密，
    # DB 层只见密文 Text，与 embedding_config.api_key / company.platform_credentials 同策略。
    # ============================================
    op.create_table(
        "platform_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column(
            "access_token", sa.Text(), nullable=True
        ),  # 应用层 EncryptedText 加密，DB 层只见密文
        sa.Column(
            "refresh_token", sa.Text(), nullable=True
        ),  # 应用层 EncryptedText 加密，DB 层只见密文
        sa.Column(
            "expires_at", sa.DateTime(), nullable=True
        ),  # access_token 过期时间，定时扫描依据
        sa.Column("refresh_expires_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("company_id", "platform", name="uq_platform_token_company_platform"),
    )
    op.create_index("ix_platform_tokens_id", "platform_tokens", ["id"])
    op.create_index("ix_platform_tokens_company_id", "platform_tokens", ["company_id"])
    op.create_index("ix_platform_tokens_platform", "platform_tokens", ["platform"])
    op.create_index("ix_platform_tokens_expires_at", "platform_tokens", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_platform_tokens_expires_at", table_name="platform_tokens")
    op.drop_index("ix_platform_tokens_platform", table_name="platform_tokens")
    op.drop_index("ix_platform_tokens_company_id", table_name="platform_tokens")
    op.drop_index("ix_platform_tokens_id", table_name="platform_tokens")
    op.drop_table("platform_tokens")
