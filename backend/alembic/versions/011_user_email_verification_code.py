"""add email verification code fields to users

Revision ID: 011_user_email_verification_code
Revises: 010_evolution_log_training_data_path
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "011_user_email_verification_code"
down_revision: str | None = "010_evolution_log_training_data_path"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    if "email_verified" not in columns:
        op.add_column(
            "users",
            sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    if "email_verified_at" not in columns:
        op.add_column("users", sa.Column("email_verified_at", sa.DateTime(), nullable=True))
    if "email_verification_code_hash" not in columns:
        op.add_column(
            "users",
            sa.Column("email_verification_code_hash", sa.String(length=128), nullable=True),
        )
    if "email_verification_expires_at" not in columns:
        op.add_column(
            "users",
            sa.Column("email_verification_expires_at", sa.DateTime(), nullable=True),
        )
    if "email_verification_sent_at" not in columns:
        op.add_column(
            "users",
            sa.Column("email_verification_sent_at", sa.DateTime(), nullable=True),
        )
    if "email_verification_attempts" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "email_verification_attempts",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )
    op.create_index(
        "ix_users_email_verified",
        "users",
        ["email_verified"],
        if_not_exists=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    try:
        op.drop_index("ix_users_email_verified", table_name="users", if_exists=True)
    except TypeError:
        op.drop_index("ix_users_email_verified", table_name="users")

    for column_name in (
        "email_verification_attempts",
        "email_verification_sent_at",
        "email_verification_expires_at",
        "email_verification_code_hash",
        "email_verified_at",
        "email_verified",
    ):
        if column_name in columns:
            op.drop_column("users", column_name)
