"""add browser connector capture jobs

Revision ID: 012_capture_jobs
Revises: 011_user_email_verification_code, 003_browser_connector_events
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "012_capture_jobs"
down_revision: tuple[str, str] = (
    "011_user_email_verification_code",
    "003_browser_connector_events",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "capture_jobs" in set(inspector.get_table_names()):
        return

    op.create_table(
        "capture_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("source_message_id", sa.Integer(), nullable=True),
        sa.Column("purpose", sa.String(length=40), nullable=False, server_default="generic_evidence"),
        sa.Column("target_host", sa.String(length=255), nullable=False),
        sa.Column("target_path_prefix", sa.String(length=1024), nullable=False, server_default="/"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("capture_limit", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("capture_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("capability_ticket_hash", sa.String(length=64), nullable=False),
        sa.Column("ticket_expires_at", sa.DateTime(), nullable=False),
        sa.Column("ticket_used_at", sa.DateTime(), nullable=True),
        sa.Column("result_event_id", sa.Integer(), nullable=True),
        sa.Column("classification", sa.String(length=40), nullable=True),
        sa.Column("result_summary_json", sa.Text(), nullable=True),
        sa.Column("draft_kind", sa.String(length=32), nullable=True),
        sa.Column("draft_content", sa.Text(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_capture_jobs_company_id", "capture_jobs", ["company_id"])
    op.create_index("ix_capture_jobs_user_id", "capture_jobs", ["user_id"])
    op.create_index("ix_capture_jobs_conversation_id", "capture_jobs", ["conversation_id"])
    op.create_index("ix_capture_jobs_status", "capture_jobs", ["status"])
    op.create_index("ix_capture_jobs_expires_at", "capture_jobs", ["expires_at"])
    op.create_index("ix_capture_jobs_result_event_id", "capture_jobs", ["result_event_id"])
    op.create_index("ix_capture_jobs_conversation_updated", "capture_jobs", ["conversation_id", "updated_at"])
    op.create_index("ix_capture_jobs_owner_status", "capture_jobs", ["company_id", "user_id", "status"])


def downgrade() -> None:
    bind = op.get_bind()
    if "capture_jobs" not in set(sa.inspect(bind).get_table_names()):
        return
    for index_name in (
        "ix_capture_jobs_owner_status",
        "ix_capture_jobs_conversation_updated",
        "ix_capture_jobs_result_event_id",
        "ix_capture_jobs_expires_at",
        "ix_capture_jobs_status",
        "ix_capture_jobs_conversation_id",
        "ix_capture_jobs_user_id",
        "ix_capture_jobs_company_id",
    ):
        try:
            op.drop_index(index_name, table_name="capture_jobs", if_exists=True)
        except TypeError:
            op.drop_index(index_name, table_name="capture_jobs")
    op.drop_table("capture_jobs")
