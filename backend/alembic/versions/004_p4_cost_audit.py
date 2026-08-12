"""add task_type column to cost_records and create audit_log table

Revision ID: 004_p4_cost_audit
Revises: 003_embedding_config
Create Date: 2026-06-30

P4 增强数据库结构变更（将运行时兜底的 ALTER/CREATE 正式纳入版本管理）：
1. cost_records 表新增 task_type 列（按任务类型归因 LLM 调用成本）
2. 新建 audit_log 表（记录关键操作审计日志）

此前由 app.services.model_gateway.CostAttributor / AuditLogger 通过
ALTER TABLE ADD COLUMN IF NOT EXISTS / CREATE TABLE IF NOT EXISTS 兜底创建，
本 migration 将其正式纳入 Alembic 版本管理，供全新部署直接 upgrade 到位。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004_p4_cost_audit"
down_revision: str | None = "003_embedding_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ============================================
    # 1. cost_records 新增 task_type 列
    # 按任务类型（如 chat / tool_call / rag）归因 LLM 调用成本
    # 与 CostAttributor._ensure_table_schema 的运行时 ALTER 兜底对齐
    # ============================================
    op.add_column("cost_records", sa.Column("task_type", sa.String(50), nullable=True))

    # ============================================
    # 2. audit_log — 审计日志表（P4 新增）
    # 与 AuditLogger._ensure_table 的运行时 CREATE TABLE IF NOT EXISTS 对齐
    # 字段：id / company_id / user_id / action / resource / metadata_json / created_at
    # ============================================
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource", sa.String(255), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_id", "audit_log", ["id"])
    op.create_index("ix_audit_log_company_id", "audit_log", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_company_id", table_name="audit_log")
    op.drop_index("ix_audit_log_id", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_column("cost_records", "task_type")
