"""
数据迁移脚本：将 SQLite 数据迁移到 PostgreSQL
"""

import os
import sqlite3

import psycopg2

# SQLite 数据库路径
SQLITE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "feedback.db")

def get_postgres_url() -> str:
    """Read the target PostgreSQL URL at execution time."""
    pg_url = os.getenv("DATABASE_URL", "").strip()
    if not pg_url.startswith(("postgresql://", "postgres://")):
        raise RuntimeError("Set DATABASE_URL to a PostgreSQL connection string before migrating")
    if "agentx" + "_password" in pg_url:
        raise RuntimeError("Refusing to use weak default PostgreSQL password in DATABASE_URL")
    return pg_url

def migrate():
    """执行数据迁移"""
    print("开始数据迁移...")
    pg_url = get_postgres_url()

    # 检查 SQLite 文件是否存在
    if not os.path.exists(SQLITE_PATH):
        print(f"警告: SQLite 数据库文件不存在: {SQLITE_PATH}")
        print("跳过迁移，但会确保 PostgreSQL 表已创建")
        create_postgres_tables()
        return

    try:
        # 1. 连接 SQLite
        print(f"连接 SQLite 数据库: {SQLITE_PATH}")
        sqlite_conn = sqlite3.connect(SQLITE_PATH)
        sqlite_cur = sqlite_conn.cursor()

        # 2. 连接 PostgreSQL
        print("连接 PostgreSQL 数据库: DATABASE_URL")
        pg_conn = psycopg2.connect(pg_url)
        pg_cur = pg_conn.cursor()

        # 3. 确保 PostgreSQL 表已创建
        create_postgres_tables()

        # 4. 获取 SQLite 中所有表名
        sqlite_cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in sqlite_cur.fetchall()]
        print(f"发现表: {tables}")

        # 5. 对每个表：读取数据 → 写入 PostgreSQL
        for table in tables:
            # 跳过系统表
            if table.startswith("sqlite_"):
                continue

            print(f"迁移表: {table}")

            try:
                # 获取表结构
                sqlite_cur.execute(f"PRAGMA table_info({table})")
                columns_info = sqlite_cur.fetchall()
                columns = [col[1] for col in columns_info]

                # 读取 SQLite 数据
                sqlite_cur.execute(f"SELECT * FROM {table}")
                rows = sqlite_cur.fetchall()

                if not rows:
                    print(f"  表 {table} 无数据，跳过")
                    continue

                # 写入 PostgreSQL
                placeholders = ",".join(["%s"] * len(columns))
                col_names = ",".join([f'"{col}"' for col in columns])

                for row in rows:
                    try:
                        pg_cur.execute(f'INSERT INTO {table} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING', row)
                    except psycopg2.Error as e:
                        print(f"  警告: 插入数据失败: {e}")
                        continue

                print(f"  表 {table} 迁移完成，共 {len(rows)} 行")

            except Exception as e:
                print(f"  错误: 迁移表 {table} 失败: {e}")
                continue

        # 6. 提交事务
        pg_conn.commit()
        print("数据迁移完成！")

    except Exception as e:
        print(f"迁移过程中发生错误: {e}")
        raise
    finally:
        # 7. 关闭连接
        if 'sqlite_conn' in locals():
            sqlite_conn.close()
        if 'pg_conn' in locals():
            pg_conn.close()

def create_postgres_tables():
    """确保 PostgreSQL 表已创建"""
    try:
        from app.database.core import init_database
        init_database()
        print("PostgreSQL 表创建完成")
    except Exception as e:
        print(f"创建 PostgreSQL 表失败: {e}")
        raise

if __name__ == "__main__":
    migrate()
