"""Persistent, owner-bound readonly chat tasks (no legacy queue backfill)."""
import sqlalchemy as sa

from alembic import op

revision = "015_conversation_tasks"
down_revision = "014_ensure_company_knowledge"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "conversation_tasks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("model_key", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("result", sa.Text()), sa.Column("error_code", sa.String(100)),
        sa.Column("result_message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime()), sa.Column("completed_at", sa.DateTime()),
    )
    op.create_index("ix_conversation_tasks_owner", "conversation_tasks", ["company_id", "user_id", "conversation_id"])


def downgrade():
    op.drop_index("ix_conversation_tasks_owner", table_name="conversation_tasks")
    op.drop_table("conversation_tasks")
