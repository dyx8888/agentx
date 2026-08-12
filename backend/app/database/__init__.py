"""
Database Manager and Adapters
Handles database connections and operations for both SQLite and PostgreSQL
"""

import sqlite3
from datetime import datetime

from pydantic import BaseModel

from app.core.logging import get_logger

from . import models
from .models import Agent as ORMAgent
from .models import Company as ORMCompany
from .models import User as ORMUser

logger = get_logger(__name__)


# Pydantic models for data validation
class UserPydantic(BaseModel):
    id: int | None = None
    username: str
    password_hash: str
    company_id: int | None = None
    is_admin: bool = False
    disabled: bool = False
    created_at: datetime | None = None


class CompanyPydantic(BaseModel):
    id: int | None = None
    name: str
    brand_name: str
    category: str
    platforms_json: str
    llm_api_key: str | None = None
    created_at: datetime | None = None


class AgentPydantic(BaseModel):
    id: int | None = None
    company_id: int
    name: str
    description: str
    tools_json: str
    created_at: datetime | None = None


class TaskPydantic(BaseModel):
    id: int | None = None
    company_id: int
    source_agent_id: int | None = None
    target_agent_name: str | None = None
    task_description: str
    status: str
    result: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class FeedbackPydantic(BaseModel):
    id: int | None = None
    session_id: str
    tool_name: str
    original_output: str
    human_edited_output: str
    kol_name: str | None = None
    product_name: str | None = None
    company_id: str = "default"
    agent_id: str | None = None


class EvolutionLogPydantic(BaseModel):
    id: int | None = None
    agent_id: int
    tool_name: str | None = None
    suggestion_text: str
    training_data_path: str | None = None
    applied: bool = False


# 注意：以下别名将 Pydantic 校验模型导出为 User/Company/Agent 等，
# 与 app.database.models 中的同名 ORM 类存在命名冲突。
# 历史上有 18+ 个文件通过 `from app.database import User` 导入此处的 Pydantic 版本，
# 改名影响面较大故保持原状；如需引用 ORM 类请使用 `from app.database.models import User as ORMUser`
# 或本文件末尾已导出的 ORMUser/ORMCompany/ORMAgent 别名。
User = UserPydantic
Company = CompanyPydantic
Agent = AgentPydantic
Task = TaskPydantic
Feedback = FeedbackPydantic
EvolutionLog = EvolutionLogPydantic


class DatabaseManager:
    """Database Manager Interface"""

    def get_connection(self):
        raise NotImplementedError("Subclasses must implement get_connection")

    def init_database(self):
        raise NotImplementedError("Subclasses must implement init_database")


class SQLiteDatabaseManager(DatabaseManager):
    """SQLite Database Manager (fallback only)"""

    def __init__(self, db_path="agentx.db"):
        self.db_path = db_path

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        return conn

    def init_database(self):
        from app.database import core

        core.init_database()
        logger.info("sqlite_tables_created")

    def close_connection(self, conn):
        conn.close()


class DatabaseProxy:
    """Lazy proxy that delegates all attribute access to the real database adapter.

    All modules import `db` from this package at module load time (before
    init_database() is called in the lifespan). The proxy ensures that
    attribute access is always routed to the current adapter instance.
    """

    _instance = None

    def __getattr__(self, name):
        if self._instance is None:
            raise RuntimeError("Database not initialized. Call app.database.init_database() first.")
        return getattr(self._instance, name)

    def _set_instance(self, adapter):
        self._instance = adapter


db = DatabaseProxy()


def init_database():
    """Initialize database based on environment"""

    from .core import init_database as init_core
    from .postgres_adapter import PostgresAdapter

    init_core()

    adapter = PostgresAdapter()
    db._set_instance(adapter)
    logger.info("database_initialized", engine_type=adapter.engine.dialect.name)


__all__ = [
    "User",
    "Company",
    "Agent",
    "Task",
    "Feedback",
    "EvolutionLog",
    "DatabaseManager",
    "SQLiteDatabaseManager",
    "db",
    "init_database",
    "models",
    "ORMAgent",
    "ORMCompany",
    "ORMUser",
]
