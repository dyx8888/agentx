"""add user token version

Revision ID: 009_user_token_version
Revises: 008_kol_source_fields
Create Date: 2026-08-09

Add a user-level token_version so password changes and password resets can
invalidate all previously issued access and refresh tokens without storing every
historical token jti.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009_user_token_version"
down_revision: str | None = "008_kol_source_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" not in tables:
        return

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "token_version" not in user_columns:
        op.add_column(
            "users",
            sa.Column(
                "token_version",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" not in tables:
        return

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "token_version" in user_columns:
        op.drop_column("users", "token_version")
