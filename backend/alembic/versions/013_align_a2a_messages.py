"""align legacy a2a_messages columns with the ORM model

Revision ID: 013_align_a2a_messages
Revises: 012_capture_jobs
Create Date: 2026-09-12
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "013_align_a2a_messages"
down_revision: str | None = "012_capture_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


RENAMED_COLUMNS = {
    "sender": ("sender_agent_name", sa.String(length=100)),
    "recipients": ("recipient_agent_name", sa.Text()),
    "task": ("task_description", sa.Text()),
    "payload_json": ("payload", sa.Text()),
}


def _column_names(bind) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns("a2a_messages")}


def _index_names(bind) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes("a2a_messages")}


def upgrade() -> None:
    bind = op.get_bind()
    if "a2a_messages" not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            "a2a_messages",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("message_id", sa.String(length=64), nullable=False),
            sa.Column("sender_agent_name", sa.String(length=100), nullable=False),
            sa.Column("recipient_agent_name", sa.Text(), nullable=False),
            sa.Column("task_description", sa.Text(), nullable=False),
            sa.Column("task_type", sa.String(length=50), nullable=False),
            sa.Column("payload", sa.Text(), nullable=True),
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("result", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("message_id", name="uq_a2a_messages_message_id"),
        )
    else:
        columns = _column_names(bind)
        with op.batch_alter_table("a2a_messages") as batch_op:
            for old_name, (new_name, existing_type) in RENAMED_COLUMNS.items():
                if old_name in columns and new_name not in columns:
                    batch_op.alter_column(
                        old_name,
                        new_column_name=new_name,
                        existing_type=existing_type,
                    )

        columns = _column_names(bind)
        additions = {
            "message_id": sa.Column("message_id", sa.String(length=64), nullable=True),
            "result": sa.Column("result", sa.Text(), nullable=True),
            "completed_at": sa.Column("completed_at", sa.DateTime(), nullable=True),
        }
        with op.batch_alter_table("a2a_messages") as batch_op:
            for name, column in additions.items():
                if name not in columns:
                    batch_op.add_column(column)

        rows = bind.execute(
            sa.text("SELECT id FROM a2a_messages WHERE message_id IS NULL")
        ).fetchall()
        for row in rows:
            bind.execute(
                sa.text(
                    "UPDATE a2a_messages SET message_id = :message_id WHERE id = :row_id"
                ),
                {"message_id": uuid.uuid4().hex, "row_id": row[0]},
            )

        null_companies = bind.execute(
            sa.text("SELECT COUNT(*) FROM a2a_messages WHERE company_id IS NULL")
        ).scalar_one()
        with op.batch_alter_table("a2a_messages") as batch_op:
            batch_op.alter_column(
                "message_id",
                existing_type=sa.String(length=64),
                nullable=False,
            )
            if not null_companies:
                batch_op.alter_column(
                    "company_id",
                    existing_type=sa.Integer(),
                    nullable=False,
                )

        unique_names = {
            constraint["name"]
            for constraint in sa.inspect(bind).get_unique_constraints("a2a_messages")
        }
        if "uq_a2a_messages_message_id" not in unique_names:
            with op.batch_alter_table("a2a_messages") as batch_op:
                batch_op.create_unique_constraint(
                    "uq_a2a_messages_message_id",
                    ["message_id"],
                )

    indexes = _index_names(bind)
    if "ix_a2a_messages_company_id" not in indexes:
        op.create_index(
            "ix_a2a_messages_company_id",
            "a2a_messages",
            ["company_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "a2a_messages" not in set(sa.inspect(bind).get_table_names()):
        return

    if "ix_a2a_messages_company_id" in _index_names(bind):
        op.drop_index("ix_a2a_messages_company_id", table_name="a2a_messages")

    columns = _column_names(bind)
    with op.batch_alter_table("a2a_messages") as batch_op:
        if "completed_at" in columns:
            batch_op.drop_column("completed_at")
        if "result" in columns:
            batch_op.drop_column("result")
        if "message_id" in columns:
            batch_op.drop_column("message_id")
        for old_name, (new_name, existing_type) in RENAMED_COLUMNS.items():
            if new_name in columns and old_name not in columns:
                batch_op.alter_column(
                    new_name,
                    new_column_name=old_name,
                    existing_type=existing_type,
                )
