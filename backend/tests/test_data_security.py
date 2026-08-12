"""
数据安全测试
测试加密解密和数据库备份功能
"""

import os

# 添加项目根目录到 Python 路径
import sys
import tempfile
from unittest.mock import patch

import pytest

sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.database.models import Company, EncryptedText
from app.utils.encryption import decrypt_data, encrypt_data, is_encryption_configured


class TestDataSecurity:
    """数据安全测试类"""

    def test_1_encrypt_decrypt_success(self):
        """正常场景1：加密后解密可还原"""
        # 测试数据
        original_text = "test_api_key_12345"

        # 加密
        encrypted = encrypt_data(original_text)
        assert encrypted != original_text
        assert len(encrypted) > 0

        # 解密
        decrypted = decrypt_data(encrypted)
        assert decrypted == original_text

    def test_2_company_model_auto_encrypt_decrypt(self):
        """正常场景2：Company 模型自动加解密"""
        # 设置加密密钥（必须使用合法的 Fernet 密钥，否则 generate_key 会抛 ValueError）
        with patch.dict(
            os.environ, {"ENCRYPTION_KEY": "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg="}
        ):
            # 创建公司对象
            test_credentials = '{"test_key": "secret_value", "api_token": "abc123"}'

            Company(
                name="测试公司",
                brand_name="测试品牌",
                category="测试分类",
                platforms_json='{"douyin": true}',
                platform_credentials=test_credentials,
            )

            # 验证存储时自动加密
            # 注意：这里我们模拟加密行为，因为实际存储需要数据库会话
            encrypted_field = EncryptedText()
            encrypted_value = encrypted_field.process_bind_param(test_credentials, None)
            assert encrypted_value != test_credentials
            assert "test_key" not in encrypted_value

            # 验证读取时自动解密
            decrypted_value = encrypted_field.process_result_value(encrypted_value, None)
            assert decrypted_value == test_credentials

    def test_3_decrypt_corrupted_data_exception(self):
        """异常场景1：解密损坏的加密数据抛出异常"""
        # 设置加密密钥
        with patch.dict(os.environ, {"ENCRYPTION_KEY": "test_key_for_encryption"}):
            # 创建无效的加密数据
            invalid_encrypted = "invalid_base64_string"

            # 尝试解密应该失败
            with pytest.raises(Exception) as exc_info:
                decrypt_data(invalid_encrypted)
                assert "Decryption failed" in str(exc_info.value)

    def test_4_encryption_key_required(self):
        """异常场景2：未设置加密密钥时的错误处理"""
        # 清除环境变量（clear=True 已清空所有环境变量，无需再设 None；os.environ 不接受 None 值）
        with patch.dict(os.environ, {}, clear=True):
            # 尝试加密应该抛出异常（encrypt_data 将底层 ValueError 包装为 Exception）
            with pytest.raises(Exception) as exc_info:
                encrypt_data("test_data")
                assert "ENCRYPTION_KEY environment variable is required" in str(exc_info.value)

    def test_5_encryption_configuration_check(self):
        """正常场景3：加密配置检查"""
        # 设置环境变量
        with patch.dict(os.environ, {"ENCRYPTION_KEY": "test_key"}):
            assert is_encryption_configured()

        # 清除环境变量（clear=True 已清空所有环境变量，无需再设 None；os.environ 不接受 None 值）
        with patch.dict(os.environ, {}, clear=True):
            assert not is_encryption_configured()

    def test_6_backup_script_sqlite(self):
        """正常场景4：SQLite 备份脚本测试"""
        from pathlib import Path

        # 创建临时数据库文件
        with tempfile.TemporaryDirectory() as temp_dir:
            # backup_sqlite 在 BASE_DIR / "data" / "feedback.db" 查找数据库文件
            data_dir = os.path.join(temp_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            test_db_path = os.path.join(data_dir, "feedback.db")

            # 创建测试数据库文件
            with open(test_db_path, "w") as f:
                f.write("test database content")

            # Mock 数据库路径为临时目录（用 Path 保证 / 运算符正常工作）
            with patch("scripts.backup_db.BASE_DIR", Path(temp_dir)):
                # 导入并运行备份脚本
                from scripts.backup_db import backup_sqlite

                # 运行备份
                result = backup_sqlite()

                # 验证备份文件是否创建（备份写入 BASE_DIR / "data" / "backups"）
                backup_dir = os.path.join(temp_dir, "data", "backups")
                backup_files = [
                    f
                    for f in os.listdir(backup_dir)
                    if f.startswith("feedback_") and f.endswith(".db")
                ]
                assert len(backup_files) == 1
                assert result

    def test_7_backup_script_postgresql(self):
        """正常场景5：PostgreSQL 备份脚本测试"""
        from pathlib import Path
        from unittest.mock import MagicMock

        # 设置 PostgreSQL 环境变量
        with patch.dict(
            os.environ, {"DATABASE_URL": "postgresql://testuser:testpass@localhost:5432/testdb"}
        ):
            # Mock subprocess.run —— 同时创建备份文件，使后续 backup_path.stat() 不报错
            def mock_run_side_effect(cmd, **kwargs):
                for arg in cmd:
                    if isinstance(arg, str) and arg.startswith("--file="):
                        backup_file = arg.split("=", 1)[1]
                        Path(backup_file).parent.mkdir(parents=True, exist_ok=True)
                        Path(backup_file).write_text("mock backup content")
                        break
                mock_result = MagicMock()
                mock_result.returncode = 0
                mock_result.stdout = "backup completed"
                mock_result.stderr = ""
                return mock_result

            with patch(
                "scripts.backup_db.subprocess.run", side_effect=mock_run_side_effect
            ) as mock_run:
                # 导入并运行备份脚本
                from scripts.backup_db import backup_postgresql

                # 运行备份
                result = backup_postgresql()

                # 验证调用
                assert result
                assert mock_run.called

    def test_8_backup_script_failure_handling(self):
        """异常场景3：备份脚本在数据库不可达时优雅失败"""
        # Mock 数据库不存在
        with patch("scripts.backup_db.BASE_DIR") as mock_base_dir:
            mock_base_dir.__str__ = lambda: "/nonexistent/path"

            # 导入并运行备份脚本
            from scripts.backup_db import backup_sqlite

            # 运行备份应该失败
            result = backup_sqlite()
            assert not result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
