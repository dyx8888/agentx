"""add embedding_config table

Revision ID: 003_embedding_config
Revises: 002_mvp_tables
Create Date: 2026-06-29

Add embedding_config table for hybrid embedding mode (T1.3)：
- 每公司一条配置 (company_id unique)
- mode 支持 local / api_siliconflow / api_deepseek / api_openai
- api_key 字段使用 EncryptedText 透明加密，落盘为密文
- 配合 T1.1 的 EmbeddingService 和 T1.2 的 REST API 实现热切换
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_embedding_config"
down_revision: str | None = "002_mvp_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ============================================
    # embedding_config — 嵌入服务配置表（每公司一条）
    # ============================================
    op.create_table(
        "embedding_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False, server_default="local"),
        sa.Column("api_base_url", sa.String(500), nullable=True),
        sa.Column(
            "api_key", sa.Text(), nullable=True
        ),  # 应用层通过 EncryptedText TypeDecorator 加密，DB 层只见密文 Text
        sa.Column("model_name", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("company_id", name="uq_embedding_config_company_id"),  # 每公司一条配置
    )
    op.create_index("ix_embedding_config_id", "embedding_config", ["id"])
    op.create_index("ix_embedding_config_company_id", "embedding_config", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_embedding_config_company_id", table_name="embedding_config")
    op.drop_index("ix_embedding_config_id", table_name="embedding_config")
    op.drop_table("embedding_config")
