"""
Database Core - SQLAlchemy Session Management
Provides database session management and engine configuration
"""

import os  # 通过环境变量注入数据库连接信息，避免硬编码，支持不同部署环境灵活切换

from sqlalchemy import create_engine  # SQLAlchemy 核心工厂函数，统一不同数据库后端的创建入口
from sqlalchemy.orm import Session, sessionmaker  # Session 用于类型标注以提升 IDE 智能提示；sessionmaker 是会话工厂模式
from sqlalchemy.pool import StaticPool  # SQLite 不支持多连接并发写，需要用单连接池避免 "database is locked" 错误

from app.core.logging import get_logger  # 结构化日志，方便在分布式环境中按模块追踪数据库初始化状态

from .models import Base  # 所有 ORM 模型共享同一个 declarative_base，建表时只需遍历一次 metadata

logger = get_logger(__name__)  # 模块级 logger，按 __name__ 自动生成层级命名空间，便于日志过滤

# 模块级单例变量，采用懒初始化模式：
# 不在 import 时直接初始化 engine，而是等到 FastAPI 启动事件中调用 init_database()，
# 这样可以确保环境变量已被加载、日志系统已就绪
_engine = None
_SessionLocal = None

def init_database():
    """Initialize database engine based on configuration"""
    global _engine, _SessionLocal  # 必须声明 global，否则 Python 会在函数内部创建同名局部变量而非修改模块级单例

    database_url = os.getenv("DATABASE_URL")  # 从环境变量读取，Docker/docker-compose 中注入，本地开发可在 .env 中配置

    if database_url and database_url.startswith("postgresql"):
        # 生产环境走 PostgreSQL——成熟的关系型数据库，支持连接池、并发读写、行级锁
        logger.info("database_postgres_initializing")
        _engine = create_engine(
            database_url,
            pool_pre_ping=True,  # 每次从连接池取出连接时先发一条 SELECT 1 探测存活，防止使用已被数据库服务端关闭的僵尸连接
            pool_recycle=300,  # 每 300 秒强制回收连接，防止数据库端（如 PgBouncer/RDS）先于客户端断开空闲连接导致报错
            echo=False  # 生产环境禁止打印 SQL，避免泄露敏感数据和撑爆日志文件
        )
    else:
        # SQLite 作为兜底方案：零配置、无需独立数据库进程，适合本地开发和单机测试
        logger.info("database_sqlite_initializing")
        db_filename = "test_agentx.db" if os.getenv("TEST_MODE") == "true" else "agentx.db"  # 测试模式使用独立数据库文件，防止污染开发数据
        db_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),  # 向上三层：core.py -> database -> app -> backend
            "data",  # 统一放在 data/ 目录下，方便 .gitignore 忽略和 Docker volume 挂载
            db_filename
        )

        _engine = create_engine(
            f"sqlite:///{db_path}",
            poolclass=StaticPool,  # SQLite 是文件级锁，多个连接同时写会触发 "database is locked"；StaticPool 保证全局只有一个连接
            connect_args={
                "check_same_thread": False,  # FastAPI 的请求处理线程和创建 engine 的线程不同，SQLite 默认禁止跨线程使用同一连接，必须关闭此检查
                "timeout": 20  # 写锁等待超时设为 20 秒，比默认的 5 秒更宽容，避免高并发时频繁抛异常
            },
            echo=False
        )

    # 会话工厂配置：autocommit=False 要求显式提交事务，防止意外写入；
    # autoflush=False 避免查询前自动 flush 脏数据导致隐式 DB 操作，提升性能并让行为可预测
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

    # create_all 是幂等操作——已存在的表不会重复创建，因此可以安全地在每次启动时调用，
    # 这样新增模型后无需手动执行 DDL 脚本
    logger.info("database_creating_tables")
    Base.metadata.create_all(bind=_engine)
    logger.info("database_tables_created")

def get_session() -> Session:
    """
    Get database session dependency for FastAPI
    Returns a new session that should be closed after use
    """
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")  # 快速失败比 NoneType AttributeError 更易排查

    return _SessionLocal()  # 每次调用都创建新会话，满足 FastAPI 依赖注入的"每请求一会话"模式，避免会话跨请求共享导致数据污染

def get_engine():
    """Get the database engine"""
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")  # 防御性检查，Alembic 迁移和原生 SQL 操作依赖 engine 实例

    return _engine

def close_database():
    """Close database connections"""
    global _engine, _SessionLocal  # 需要将模块级变量置回 None 以支持重新初始化（例如测试环境 tearDown）

    if _engine:
        _engine.dispose()  # 释放连接池中所有连接，优雅关闭时避免连接泄漏和服务端残留连接
        logger.info("database_connections_closed")

# FastAPI 依赖注入式的数据库会话获取函数：
# 利用生成器的 yield 语法，FastAPI 会在请求进入时获取会话、请求结束时自动执行 finally 块关闭会话，
# 这样路由函数无需手动管理会话生命周期，减少遗漏关闭导致的连接泄漏风险
def get_db():
    """
    FastAPI dependency for database session
    Automatically handles session lifecycle
    """
    db = get_session()
    try:
        yield db  # yield 将控制权交给 FastAPI，让框架在路由函数中使用该会话
    finally:
        db.close()  # 无论请求成功还是抛异常，都会执行此处关闭操作，保证连接归还池中