"""add evolution log training data path

Revision ID: 010_evolution_log_training_data_path
Revises: 009_user_token_version
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010_evolution_log_training_data_path"
down_revision: str | None = "009_user_token_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "evolution_log" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("evolution_log")}
    if "training_data_path" not in columns:
        op.add_column("evolution_log", sa.Column("training_data_path", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "evolution_log" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("evolution_log")}
    if "training_data_path" in columns:
        op.drop_column("evolution_log", "training_data_path")
