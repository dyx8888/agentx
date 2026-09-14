"""ensure the PostgreSQL-backed lightweight RAG table

Revision ID: 014_ensure_company_knowledge
Revises: 013_align_a2a_messages
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "014_ensure_company_knowledge"
down_revision: str | None = "013_align_a2a_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "company_knowledge" not in inspector.get_table_names():
        op.create_table(
            "company_knowledge",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column(
                "company_id",
                sa.Integer(),
                sa.ForeignKey("companies.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("category", sa.String(length=50), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("embedding_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        inspector = sa.inspect(bind)

    existing_indexes = {
        index["name"] for index in inspector.get_indexes("company_knowledge") if index.get("name")
    }
    requested_indexes = {
        "ix_company_knowledge_company_id": ["company_id"],
        "ix_company_knowledge_embedding_id": ["embedding_id"],
        "ix_company_knowledge_company_embedding": ["company_id", "embedding_id"],
    }
    for name, columns in requested_indexes.items():
        if name not in existing_indexes:
            op.create_index(name, "company_knowledge", columns, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "company_knowledge" not in inspector.get_table_names():
        return
    existing_indexes = {
        index["name"] for index in inspector.get_indexes("company_knowledge") if index.get("name")
    }
    for name in (
        "ix_company_knowledge_company_embedding",
        "ix_company_knowledge_embedding_id",
        "ix_company_knowledge_company_id",
    ):
        if name in existing_indexes:
            op.drop_index(name, table_name="company_knowledge")
