# ============================================
# Alembic 配置文件 - 数据库迁移环境设置
# ============================================
# 文件作用：
# 这是 Alembic 数据库迁移工具的"入口文件"，当你运行数据库迁移命令时（如 alembic upgrade），
# Alembic 会首先执行这个文件来建立与数据库的连接。
#
# 核心功能：
# 1. 读取数据库连接信息（从环境变量或配置文件）
# 2. 加载项目的数据库模型（了解当前有哪些表、哪些字段）
# 3. 根据迁移脚本升级或降级数据库结构
#
# 工作模式：
# - 在线模式（online）：直接连接数据库执行迁移
# - 离线模式（offline）：生成 SQL 脚本，不直接执行（用于生产环境）
# ============================================


# 导入 Python 标准库 os，用于读取环境变量
import os

# 导入日志配置文件模块，用于配置日志输出
from logging.config import fileConfig

# 从 SQLAlchemy 库导入两个组件：
# - engine_from_config：根据配置创建数据库连接引擎
# - pool：连接池管理，控制数据库连接数量
from sqlalchemy import engine_from_config, pool

# 导入 Alembic 库的核心组件 context，
# context 包含当前迁移环境的所有配置信息和状态
from alembic import context

# 获取 Alembic 的配置对象，这个对象包含了 alembic.ini 中的所有配置
config = context.config

# fileConfig 函数读取配置文件（如 alembic.ini）中的日志配置，
# config.config_file_name 默认指向 alembic.ini
fileConfig(config.config_file_name)

# 获取数据库连接地址（URL）
# 优先从环境变量 DATABASE_URL 读取，如果环境变量不存在，
# 则从 Alembic 配置文件（alembic.ini）的 sqlalchemy.url 获取
# 这样设计是为了：开发环境用环境变量，生产环境用配置文件
database_url = os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url"))

# 将获取到的数据库 URL 设置为 Alembic 配置的主选项
# 这样后续所有数据库操作都会使用这个 URL
config.set_main_option("sqlalchemy.url", database_url)

# 从项目代码中导入数据库模型的"基类" Base
# Base 是 SQLAlchemy 用来定义数据库模型的基类，它包含了所有定义的表结构信息
# 当我们运行迁移时，Alembic 需要知道当前项目有哪些表、哪些字段
from app.database.models import Base

# 获取数据库模型的元数据（metadata）
# 元数据可以理解为"关于数据的数据"，它描述了所有表结构：表名、字段名、字段类型、主键、外键等
# target_metadata 会告诉 Alembic "你想要什么样的数据库结构"
target_metadata = Base.metadata


# 定义"离线迁移"函数
# 离线模式不会直接连接数据库，而是生成 SQL 脚本文件，
# 适用于：生产环境不允许直接操作数据库、需要提前审核 SQL、需要在多台机器执行
def run_migrations_offline():
    # 获取数据库连接 URL
    url = config.get_main_option("sqlalchemy.url")
    
    # 配置 Alembic 的上下文
    # url: 数据库地址
    # target_metadata: 目标数据库结构（我们希望数据库变成什么样）
    # literal_binds=True: 将参数直接嵌入 SQL 语句（兼容性更好）
    # dialect_opts: 方言选项，paramstyle="named" 表示使用命名参数
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    
    # 开始一个数据库事务
    # with context.begin_transaction(): 确保事务要么全部成功，要么全部失败
    with context.begin_transaction():
        # 执行迁移脚本中的所有迁移操作（创建表、添加字段等）
        context.run_migrations()


# 定义"在线迁移"函数
# 在线模式直接连接数据库并执行迁移，适用于开发和测试环境
def run_migrations_online():
    # engine_from_config 根据配置创建数据库连接引擎
    # get_section 读取配置文件中的 [alembic:] 小节
    # prefix="sqlalchemy." 表示配置项的前缀是 sqlalchemy.
    # poolclass=pool.NullPool 表示使用空连接池（每次操作后关闭连接）
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    
    # 建立数据库连接
    with connectable.connect() as connection:
        # 配置 Alembic 上下文，传入数据库连接
        context.configure(connection=connection, target_metadata=target_metadata)
        
        # 开始数据库事务
        with context.begin_transaction():
            # 执行迁移脚本中的所有迁移操作
            context.run_migrations()


# 程序入口：判断使用哪种模式
# is_offline_mode() 检查是否指定了 --offline 参数
# 如果是离线模式，运行离线迁移函数
# 否则运行在线迁移函数
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
