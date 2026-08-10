"""
数据加密工具模块
提供 AES-256 加密解密工具函数
"""

import base64
import os

from cryptography.fernet import Fernet

from app.core.logging import get_logger

logger = get_logger(__name__)

_encryption_key = None


def generate_key() -> bytes:
    global _encryption_key

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
                "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")

    if os.getenv("ENVIRONMENT") == "development":
        logger.warning("encryption_key_missing_dev_fallback")
        temp_key = Fernet.generate_key()
        _encryption_key = temp_key
        return temp_key

    raise ValueError(
        "ENCRYPTION_KEY environment variable is required in production. "
        "Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")


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
    try:
        Fernet(new_key.encode())
        global _encryption_key
        _encryption_key = new_key.encode()
        os.environ["ENCRYPTION_KEY"] = new_key
        logger.info("encryption_key_rotated")
        return True
    except Exception as e:
        logger.error("encryption_key_rotation_failed", error=str(e))
        return False


def is_encryption_configured() -> bool:
    return os.getenv("ENCRYPTION_KEY") is not None
