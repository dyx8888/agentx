import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _load_migration():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "013_align_a2a_messages.py"
    spec = importlib.util.spec_from_file_location("a2a_migration_013", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a2a_schema_migration_upgrades_legacy_table(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE companies (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO companies (id) VALUES (239)"))
        connection.execute(
            sa.text(
                """
                CREATE TABLE a2a_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender VARCHAR(50) NOT NULL,
                    recipients TEXT NOT NULL,
                    task TEXT NOT NULL,
                    task_type VARCHAR(50) NOT NULL,
                    company_id INTEGER,
                    payload_json TEXT,
                    status VARCHAR(20),
                    created_at DATETIME
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO a2a_messages
                    (sender, recipients, task, task_type, company_id, payload_json, status)
                VALUES
                    ('master', 'brand_bd', 'draft outreach', 'general', 239, '{}', 'pending')
                """
            )
        )

        migration = _load_migration()
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        columns = {column["name"] for column in sa.inspect(connection).get_columns("a2a_messages")}
        assert {
            "message_id",
            "sender_agent_name",
            "recipient_agent_name",
            "task_description",
            "payload",
            "result",
            "completed_at",
        } <= columns
        assert not {"sender", "recipients", "task", "payload_json"} & columns

        row = connection.execute(
            sa.text(
                """
                SELECT message_id, sender_agent_name, recipient_agent_name,
                       task_description, payload, company_id
                FROM a2a_messages
                """
            )
        ).mappings().one()
        assert row["message_id"]
        assert row["sender_agent_name"] == "master"
        assert row["recipient_agent_name"] == "brand_bd"
        assert row["task_description"] == "draft outreach"
        assert row["payload"] == "{}"
        assert row["company_id"] == 239


def test_runtime_detects_merge_migration_head():
    from app.database.core import _detect_alembic_head_revision

    assert _detect_alembic_head_revision() == "013_align_a2a_messages"
