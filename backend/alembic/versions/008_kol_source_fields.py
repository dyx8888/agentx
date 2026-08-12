"""add structured KOL source fields

Revision ID: 008_kol_source_fields
Revises: 007_user_bio_llm_usage
Create Date: 2026-08-05

Add structured provenance fields for imported KOL records so public/manual/API
data can be audited without overloading the bio column.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008_kol_source_fields"
down_revision: str | None = "007_user_bio_llm_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "kol_profiles" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("kol_profiles")}
    if "source_url" not in columns:
        op.add_column("kol_profiles", sa.Column("source_url", sa.String(length=1000), nullable=True))
    if "source_note" not in columns:
        op.add_column("kol_profiles", sa.Column("source_note", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "kol_profiles" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("kol_profiles")}
    if "source_note" in columns:
        op.drop_column("kol_profiles", "source_note")
    if "source_url" in columns:
        op.drop_column("kol_profiles", "source_url")
