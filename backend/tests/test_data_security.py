"""
数据安全测试
测试加密解密和数据库备份功能
"""

import pytest
import os
import json
import tempfile
import shutil
from unittest.mock import patch

# 添加项目根目录到 Python 路径
import sys
sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database.models import Company, EncryptedText
from app.utils.encryption import encrypt_data, decrypt_data, is_encryption_configured

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
        # 设置加密密钥
        with patch.dict(os.environ, {"ENCRYPTION_KEY": "test_key_for_encryption"}):
            # 创建公司对象
            test_credentials = '{"test_key": "secret_value", "api_token": "abc123"}'
            
            company = Company(
                name="测试公司",
                brand_name="测试品牌",
                category="测试分类",
                platforms_json='{"douyin": true}',
                platform_credentials=test_credentials
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
        # 清除环境变量
        with patch.dict(os.environ, {"ENCRYPTION_KEY": None}, clear=True):
            # 尝试加密应该抛出异常
            with pytest.raises(ValueError) as exc_info:
                encrypt_data("test_data")
                assert "ENCRYPTION_KEY environment variable is required" in str(exc_info.value)
    
    def test_5_encryption_configuration_check(self):
        """正常场景3：加密配置检查"""
        # 设置环境变量
        with patch.dict(os.environ, {"ENCRYPTION_KEY": "test_key"}):
            assert is_encryption_configured() == True
        
        # 清除环境变量
        with patch.dict(os.environ, {"ENCRYPTION_KEY": None}, clear=True):
            assert is_encryption_configured() == False
    
    def test_6_backup_script_sqlite(self):
        """正常场景4：SQLite 备份脚本测试"""
        # 创建临时数据库文件
        with tempfile.TemporaryDirectory() as temp_dir:
            test_db_path = os.path.join(temp_dir, "test.db")
            
            # 创建测试数据库文件
            with open(test_db_path, 'w') as f:
                f.write("test database content")
            
            # Mock 数据库路径
            with patch('scripts.backup_db.BASE_DIR') as mock_base_dir:
                mock_base_dir.__str__ = lambda: temp_dir
                
                # 导入并运行备份脚本
                from scripts.backup_db import backup_sqlite
                
                # 运行备份
                result = backup_sqlite()
                
                # 验证备份文件是否创建
                backup_files = [f for f in os.listdir(temp_dir) if f.startswith("feedback_") and f.endswith(".db")]
                assert len(backup_files) == 1
                assert result == True
    
    def test_7_backup_script_postgresql(self):
        """正常场景5：PostgreSQL 备份脚本测试"""
        # 设置 PostgreSQL 环境变量
        with patch.dict(os.environ, {
            "DATABASE_URL": "postgresql://testuser:testpass@localhost:5432/testdb"
        }):
            # Mock subprocess.run
            with patch('scripts.backup_db.subprocess.run') as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = "backup completed"
                
                # 导入并运行备份脚本
                from scripts.backup_db import backup_postgresql
                
                # 运行备份
                result = backup_postgresql()
                
                # 验证调用
                assert result == True
                assert mock_run.called
    
    def test_8_backup_script_failure_handling(self):
        """异常场景3：备份脚本在数据库不可达时优雅失败"""
        # Mock 数据库不存在
        with patch('scripts.backup_db.BASE_DIR') as mock_base_dir:
            mock_base_dir.__str__ = lambda: "/nonexistent/path"
            
            # 导入并运行备份脚本
            from scripts.backup_db import backup_sqlite
            
            # 运行备份应该失败
            result = backup_sqlite()
            assert result == False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
