"""add browser connector event storage

Revision ID: 003_browser_connector_events
Revises: 002_mvp_tables
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "003_browser_connector_events"
down_revision: str | None = "002_mvp_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "browser_connector_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("matched_rule", sa.String(120), nullable=False),
        sa.Column("api_url_hash", sa.String(64), nullable=False),
        sa.Column("api_method", sa.String(10), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_mime", sa.String(120), nullable=True),
        sa.Column("sanitized_payload_json", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("duplicate_of_event_id", sa.Integer(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["duplicate_of_event_id"], ["browser_connector_events.id"]),
        sa.UniqueConstraint("company_id", "payload_hash", name="uq_browser_connector_event_payload"),
    )
    op.create_index("ix_browser_connector_events_id", "browser_connector_events", ["id"])
    op.create_index("ix_browser_connector_events_company_id", "browser_connector_events", ["company_id"])
    op.create_index("ix_browser_connector_events_user_id", "browser_connector_events", ["user_id"])
    op.create_index("ix_browser_connector_events_platform", "browser_connector_events", ["platform"])
    op.create_index("ix_browser_connector_events_matched_rule", "browser_connector_events", ["matched_rule"])
    op.create_index("ix_browser_connector_events_created_at", "browser_connector_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_browser_connector_events_created_at", table_name="browser_connector_events")
    op.drop_index("ix_browser_connector_events_matched_rule", table_name="browser_connector_events")
    op.drop_index("ix_browser_connector_events_platform", table_name="browser_connector_events")
    op.drop_index("ix_browser_connector_events_user_id", table_name="browser_connector_events")
    op.drop_index("ix_browser_connector_events_company_id", table_name="browser_connector_events")
    op.drop_index("ix_browser_connector_events_id", table_name="browser_connector_events")
    op.drop_table("browser_connector_events")
