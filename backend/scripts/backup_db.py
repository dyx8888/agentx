#!/usr/bin/env python3
"""
数据库备份脚本 v2
- 支持 PostgreSQL 和 SQLite
- 7 天保留策略（自动清理过期备份）
- 支持定时执行（--schedule 模式）
- 支持手动触发（--now 模式，默认）
- 备份日志记录

用法:
    python backup_db.py              # 单次备份
    python backup_db.py --schedule   # 定时备份（每 24h 一次）
    python backup_db.py --retention 7  # 自定义保留天数
"""

import os
import sys
import time
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

DEFAULT_RETENTION_DAYS = 7


def cleanup_old_backups(backup_dir: Path, retention_days: int):
    """清理超过保留期的旧备份文件"""
    if not backup_dir.exists():
        return

    cutoff = datetime.now() - timedelta(days=retention_days)
    deleted_count = 0

    for backup_file in backup_dir.glob("*"):
        if backup_file.is_file():
            mtime = datetime.fromtimestamp(backup_file.stat().st_mtime)
            if mtime < cutoff:
                backup_file.unlink()
                deleted_count += 1
                print(f"  已删除过期备份: {backup_file.name}")

    if deleted_count > 0:
        print(f"  清理完成: 删除 {deleted_count} 个过期备份（{retention_days}天前）")


def backup_sqlite(retention_days: int = DEFAULT_RETENTION_DAYS):
    """备份 SQLite 数据库"""
    try:
        db_path = BASE_DIR / "data" / "feedback.db"
        if not db_path.exists():
            print(f"SQLite 数据库未找到: {db_path}")
            return False

        backup_dir = BASE_DIR / "data" / "backups"
        backup_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"feedback_{timestamp}.db"
        backup_path = backup_dir / backup_filename

        import shutil
        shutil.copy2(db_path, backup_path)

        file_size_kb = backup_path.stat().st_size / 1024
        print(f"SQLite 备份完成: {backup_path} ({file_size_kb:.1f} KB)")

        cleanup_old_backups(backup_dir, retention_days)
        return True

    except Exception as e:
        print(f"SQLite 备份失败: {e}")
        return False


def backup_postgresql(retention_days: int = DEFAULT_RETENTION_DAYS):
    """备份 PostgreSQL 数据库"""
    try:
        database_url = os.getenv("DATABASE_URL", "")
        if not database_url or "postgresql" not in database_url.lower():
            print("PostgreSQL 数据库 URL 未配置")
            return False

        backup_dir = BASE_DIR / "data" / "backups"
        backup_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"agentx_{timestamp}.sql"
        backup_path = backup_dir / backup_filename

        try:
            import re
            match = re.match(r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)',
                               database_url)
            if not match:
                print("PostgreSQL 连接 URL 格式无效")
                return False

            user, password, host, port, database = match.groups()

            cmd = [
                "pg_dump",
                f"--host={host}",
                f"--port={port}",
                f"--username={user}",
                f"--dbname={database}",
                "--no-password",
                "--verbose",
                "--clean",
                "--no-acl",
                "--no-owner",
                f"--file={backup_path}",
            ]

            env = os.environ.copy()
            env["PGPASSWORD"] = password

            print(f"开始 PostgreSQL 备份...")
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)

            if result.returncode == 0:
                file_size_kb = backup_path.stat().st_size / 1024
                print(f"PostgreSQL 备份完成: {backup_path} ({file_size_kb:.1f} KB)")
                cleanup_old_backups(backup_dir, retention_days)
                return True
            else:
                print(f"pg_dump 失败: {result.stderr}")
                return False

        except FileNotFoundError:
            print("pg_dump 未找到，请安装 PostgreSQL 客户端工具")
            return False
        except Exception as e:
            print(f"PostgreSQL 备份失败: {e}")
            return False


def backup_now(retention_days: int = DEFAULT_RETENTION_DAYS):
    """立即执行一次备份"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始数据库备份...")

    database_url = os.getenv("DATABASE_URL", "")
    if database_url and "postgresql" in database_url.lower():
        success = backup_postgresql(retention_days)
    else:
        success = backup_sqlite(retention_days)

    if success:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 备份完成")
    else:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 备份失败")

    return success


def backup_schedule(retention_days: int = DEFAULT_RETENTION_DAYS,
                    interval_hours: int = 24):
    """定时备份循环"""
    print(f"定时备份已启动（间隔: {interval_hours}h，保留: {retention_days}天）")
    print("按 Ctrl+C 停止")

    while True:
        try:
            backup_now(retention_days)
        except Exception as e:
            print(f"备份异常: {e}")

        next_run = datetime.now() + timedelta(hours=interval_hours)
        print(f"下次备份时间: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
        time.sleep(interval_hours * 3600)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="AgentX 数据库备份工具")
    parser.add_argument("--schedule", action="store_true",
                         help="启动定时备份模式")
    parser.add_argument("--interval", type=int, default=24,
                         help="定时备份间隔（小时），默认 24")
    parser.add_argument("--retention", type=int, default=DEFAULT_RETENTION_DAYS,
                         help=f"备份保留天数，默认 {DEFAULT_RETENTION_DAYS}")

    args = parser.parse_args()

    if args.schedule:
        backup_schedule(retention_days=args.retention,
                         interval_hours=args.interval)
    else:
        success = backup_now(retention_days=args.retention)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()