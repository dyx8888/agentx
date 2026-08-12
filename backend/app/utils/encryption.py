"""
数据加密工具模块
提供 AES-256 加密解密工具函数
"""

import base64
import contextlib
import os
import re
import threading
from typing import (
    Any,  # reencrypt_all_fields 的 table_model / db_session 用 Any 标注，避免硬依赖 database 模块
)

from cryptography.fernet import Fernet

from app.core.logging import get_logger

logger = get_logger(__name__)

_encryption_key = None
_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# 开发环境固定回退密钥：仅用于 ENVIRONMENT=development 且未配置 ENCRYPTION_KEY 时。
# 必须固定，否则每次进程重启都会生成新随机密钥，导致已加密字段
# （platform_credentials、llm_api_key、EmbeddingConfig.api_key 等）全部无法解密。
# ⚠️ 生产环境必须配置 ENCRYPTION_KEY 环境变量，切勿使用此密钥。
_DEV_DEFAULT_KEY = b"ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg="

# 保护 _encryption_key 初始化的线程锁，避免并发场景下重复生成/写入
_key_lock = threading.Lock()


def _quote_sql_identifier(identifier: str) -> str:
    """Quote a trusted SQL identifier after strict validation."""
    if not _SQL_IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(f"Unsafe SQL identifier: {identifier}")
    return f'"{identifier}"'


def generate_key() -> bytes:
    global _encryption_key

    # 双检锁：避免并发线程重复初始化，参考 app/services/session_store.py 的单例锁用法
    if _encryption_key is not None:
        return _encryption_key

    with _key_lock:
        # 二次检查：防止多个线程同时通过第一次检查
        if _encryption_key is not None:
            return _encryption_key

        env_key = os.getenv("ENCRYPTION_KEY")
        if env_key:
            try:
                Fernet(env_key.encode())
                _encryption_key = env_key.encode()
                return _encryption_key
            except Exception:
                raise ValueError(
                    "ENCRYPTION_KEY environment variable is not a valid Fernet key. "
                    'Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
                )

        if os.getenv("ENVIRONMENT") == "development":
            # 明确警告：开发默认密钥已硬编码在源码中，仅限本地开发使用，
            # 生产环境必须设置 ENCRYPTION_KEY 环境变量，否则会触发下方 ValueError
            logger.warning(
                "encryption_key_missing_dev_fallback",
                message="使用开发默认 Fernet 密钥，生产环境必须设置 ENCRYPTION_KEY 环境变量",
            )
            # 使用固定 dev key，避免重启后已加密数据无法解密
            _encryption_key = _DEV_DEFAULT_KEY
            return _encryption_key

        raise ValueError(
            "ENCRYPTION_KEY environment variable is required in production. "
            'Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )


def get_encryption_key() -> bytes:
    if _encryption_key is None:
        generate_key()
    return _encryption_key


def encrypt_data(plain_text: str) -> str:
    try:
        key = generate_key()
        fernet = Fernet(key)
        encrypted_data = fernet.encrypt(plain_text.encode())
        return base64.b64encode(encrypted_data).decode()
    except Exception as e:
        raise Exception(f"Encryption failed: {str(e)}")


def decrypt_data(cipher_text: str) -> str:
    try:
        key = generate_key()
        fernet = Fernet(key)
        encrypted_data = base64.b64decode(cipher_text.encode())
        decrypted_data = fernet.decrypt(encrypted_data)
        return decrypted_data.decode()
    except Exception as e:
        if "Invalid token" in str(e):
            raise Exception("Decryption failed: Invalid encryption key or corrupted data")
        raise Exception(f"Decryption failed: {str(e)}")


def rotate_key(new_key: str) -> bool:
    # 加 _key_lock 保护：防止并发 rotate_key 之间互相覆盖，以及与 generate_key 的初始化竞争
    try:
        Fernet(new_key.encode())
        global _encryption_key
        with _key_lock:
            _encryption_key = new_key.encode()
            os.environ["ENCRYPTION_KEY"] = new_key
        # ⚠️ 重要：本方法仅切换内存中的当前加密密钥，不会自动重加密已存在的存量密文。
        # 调用方应同步执行 rotate_key_with_reencrypt（或 reencrypt_all_fields）将数据库中
        # 用旧 key 加密的字段重加密为新 key，否则旧数据将无法用新 key 解密。
        # 推荐流程：先用 rotate_key_with_reencrypt 完成存量数据重加密，再调用本方法切换密钥。
        logger.info("encryption_key_rotated")
        return True
    except Exception as e:
        logger.error("encryption_key_rotation_failed", error=str(e))
        return False


def rotate_key_with_reencrypt(
    new_key: bytes, encrypted_records: list[tuple[str, str]]
) -> list[str]:
    """用旧 key 解密每条记录，用新 key 重新加密。

    本函数以当前 _encryption_key 作为"旧 key"解密存量密文，因此必须在 rotate_key 切换
    新 key 之前调用，否则旧密文将无法解密（解密失败会被跳过并保留原密文）。

    Args:
        new_key: 新的 Fernet 密钥（bytes）
        encrypted_records: (field_name, ciphertext) 列表

    Returns:
        重加密后的密文列表，顺序与输入一一对应。
        若某条记录用旧 key 解密失败（如已用新 key 加密过、或密文损坏），
        则跳过重加密、保留原密文并记录 warning，返回列表长度仍与输入一致。
    """
    # 快照旧 key 到局部变量：避免循环过程中其他线程调用 rotate_key 导致 old_key 漂移
    old_key = get_encryption_key()
    old_fernet = Fernet(old_key)

    try:
        new_fernet = Fernet(new_key)
    except Exception as e:
        raise ValueError(f"Invalid new_key: {e}")

    new_ciphertexts: list[str] = []
    for field_name, ciphertext in encrypted_records:
        try:
            encrypted_data = base64.b64decode(ciphertext.encode())
            plaintext = old_fernet.decrypt(encrypted_data)
            new_encrypted = new_fernet.encrypt(plaintext)
            new_ciphertexts.append(base64.b64encode(new_encrypted).decode())
        except Exception as e:
            logger.warning(
                "reencrypt_record_skipped",
                field_name=field_name,
                error=str(e),
            )
            new_ciphertexts.append(ciphertext)
    return new_ciphertexts


def reencrypt_all_fields(
    table_model: Any,
    field_names: list[str],
    db_session: Any,
    new_key: bytes,
) -> int:
    """批量重加密指定表所有记录的指定字段。

    遍历整张表，对每条记录的指定字段调用 rotate_key_with_reencrypt，将旧 key 密文
    转换为新 key 密文后写回数据库。

    ⚠️ 调用时机：必须在 rotate_key(new_key) 之前调用。本函数依赖当前 _encryption_key
    作为旧 key 解密存量数据；若先切换密钥，旧密文将无法解密。

    推荐流程：
        1. 准备 new_key
        2. reencrypt_all_fields(Model, ["field1", "field2"], session, new_key)
        3. rotate_key(new_key.decode())  # 切换内存密钥

    说明：使用原生 SQL 读写以绕过 EncryptedText 的 process_bind_param / process_result_value
    自动加解密，直接操作密文，避免双重加密或解密失败回退导致的语义错乱。

    Args:
        table_model: SQLAlchemy 模型类（需有 __tablename__ 属性）
        field_names: 需要重加密的字段名列表
        db_session: SQLAlchemy session 实例
        new_key: 新的 Fernet 密钥（bytes）

    Returns:
        成功重加密（密文实际发生变化并写回）的记录数
    """
    # 延迟导入 sqlalchemy.text：避免 encryption.py 在纯加解密场景下硬依赖 sqlalchemy
    try:
        from sqlalchemy import text
    except ImportError:
        logger.error("reencrypt_sqlalchemy_missing")
        return 0

    try:
        table_name = table_model.__tablename__
    except AttributeError:
        logger.error("reencrypt_invalid_model", error="model missing __tablename__")
        return 0
    try:
        quoted_table = _quote_sql_identifier(table_name)
        quoted_fields = ", ".join(_quote_sql_identifier(field_name) for field_name in field_names)
    except ValueError as e:
        logger.error("reencrypt_invalid_identifier", error=str(e))
        return 0

    # 原生 SQL 读取原始密文，绕过 EncryptedText 的 process_result_value 自动解密
    select_sql = f"SELECT id, {quoted_fields} FROM {quoted_table}"  # nosec B608: identifiers are strictly validated above.

    try:
        rows = db_session.execute(text(select_sql)).fetchall()
    except Exception as e:
        logger.error("reencrypt_select_failed", table=table_name, error=str(e))
        return 0

    reencrypted_count = 0
    for row in rows:
        row_id = row[0]
        records_to_rotate: list[tuple[str, str]] = []
        for i, field_name in enumerate(field_names, start=1):
            ciphertext = row[i]
            if ciphertext is None:
                continue
            records_to_rotate.append((field_name, ciphertext))

        if not records_to_rotate:
            continue

        try:
            new_ciphertexts = rotate_key_with_reencrypt(new_key, records_to_rotate)
        except Exception as e:
            logger.error("reencrypt_row_failed", table=table_name, row_id=row_id, error=str(e))
            continue

        # 仅当至少一个字段密文变化时才执行 UPDATE；解密失败被跳过的记录原密文不变，无需写回
        set_parts: list[str] = []
        params: dict[str, Any] = {"row_id": row_id}
        changed = False
        for i, ((field_name, old_ct), new_ct) in enumerate(
            zip(records_to_rotate, new_ciphertexts, strict=False)
        ):
            if new_ct != old_ct:
                changed = True
            set_parts.append(f"{_quote_sql_identifier(field_name)} = :val_{i}")
            params[f"val_{i}"] = new_ct

        if not changed:
            continue

        # 原生 SQL 写回新密文，绕过 EncryptedText 的 process_bind_param 自动加密
        update_sql = f"UPDATE {quoted_table} SET {', '.join(set_parts)} WHERE id = :row_id"  # nosec B608: identifiers are strictly validated above.
        try:
            db_session.execute(text(update_sql), params)
            reencrypted_count += 1
        except Exception as e:
            logger.error("reencrypt_update_failed", table=table_name, row_id=row_id, error=str(e))

    try:
        db_session.commit()
    except Exception as e:
        logger.error("reencrypt_commit_failed", table=table_name, error=str(e))
        with contextlib.suppress(Exception):
            db_session.rollback()
        return 0

    logger.info("reencrypt_complete", table=table_name, reencrypted_count=reencrypted_count)
    return reencrypted_count


def is_encryption_configured() -> bool:
    return os.getenv("ENCRYPTION_KEY") is not None
