"""
向量数据库切换测试
测试 ChromaDB 和 Milvus 向量后端的切换和基本增删查功能
"""

import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.mcp_servers.knowledge_retrieval_server import KnowledgeRetrieval

class TestVectorBackend:
    """向量后端测试类"""
    
    @classmethod
    def setup_class(cls):
        """测试类初始化"""
        # 创建测试客户端
        cls.client = TestClient(app)
    
    def test_1_default_chromadb_success(self):
        """正常场景1：默认使用 ChromaDB"""
        # Mock 环境变量，不设置 VECTOR_DB
        with patch.dict(os.environ, {"VECTOR_DB": None}, clear=True):
            # 模拟默认行为（使用 ChromaDB）
            with patch('app.mcp_servers.knowledge_retrieval_server.chromadb.PersistentClient') as mock_chroma:
                with patch('app.mcp_servers.knowledge_retrieval_server.chromadb.PersistentClient.get_collection') as mock_get_collection:
                    with patch('app.mcp_servers.knowledge_retrieval_server.chromadb.PersistentClient.create_collection') as mock_create_collection:
                        # Mock 返回空集合（不存在）
                        mock_get_collection.return_value = None
                        mock_create_collection.return_value = MagicMock()
                        
                        # 实例化 KnowledgeRetrieval
                        retrieval = KnowledgeRetrieval("test_chroma")
                        
                        # 验证使用了 ChromaDB
                        assert retrieval.vector_db == "chromadb", "应该使用 ChromaDB"
                        assert mock_chroma.called, "应该创建 PersistentClient"
                        assert mock_get_collection.called, "应该尝试获取集合"
                        assert mock_create_collection.called, "应该创建集合"
    
    def test_2_explicit_chromadb_success(self):
        """正常场景2：显式设置 ChromaDB"""
        # Mock 环境变量，设置 VECTOR_DB=chromadb
        with patch.dict(os.environ, {"VECTOR_DB": "chromadb"}, clear=True):
            # 模拟 ChromaDB 行为
            with patch('app.mcp_servers.knowledge_retrieval_server.chromadb.PersistentClient') as mock_chroma:
                with patch('app.mcp_servers.knowledge_retrieval_server.chromadb.PersistentClient.get_collection') as mock_get_collection:
                    with patch('app.mcp_servers.knowledge_retrieval_server.chromadb.PersistentClient.create_collection') as mock_create_collection:
                        # Mock 返回已存在的集合
                        mock_get_collection.return_value = MagicMock()
                        mock_create_collection.return_value = MagicMock()
                        
                        # 实例化 KnowledgeRetrieval
                        retrieval = KnowledgeRetrieval("test_chroma")
                        
                        # 验证使用了 ChromaDB
                        assert retrieval.vector_db == "chromadb", "应该使用 ChromaDB"
                        assert mock_chroma.called, "应该创建 PersistentClient"
                        assert mock_get_collection.called, "应该尝试获取集合"
                        assert not mock_create_collection.called, "不应该创建集合（已存在）"
    
    def test_3_milvus_fallback_success(self):
        """正常场景3：Milvus 可用时的测试"""
        # Mock pymilvus 可用
        with patch.dict(os.environ, {"VECTOR_DB": "milvus"}, clear=True):
            with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus') as mock_pymilvus:
                with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.connections.connect') as mock_connect:
                    with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.Collection') as mock_collection:
                        with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.FieldSchema') as mock_field_schema:
                            with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.CollectionSchema') as mock_collection_schema:
                                with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.DataType') as mock_data_type:
                                    with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.utility') as mock_utility:
                                        # Mock 返回已存在的集合
                                        mock_collection.return_value = MagicMock()
                                        
                                        # 实例化 KnowledgeRetrieval
                                        retrieval = KnowledgeRetrieval("test_milvus")
                                        
                                        # 验证使用了 Milvus
                                        assert retrieval.vector_db == "milvus", "应该使用 Milvus"
                                        assert mock_pymilvus.connections.connect.called, "应该连接 Milvus"
                                        assert mock_collection.called, "应该获取集合"
                                        assert not mock_collection_schema.called, "不应该创建集合（已存在）"
    
    def test_4_milvus_unavailable_graceful_fallback(self):
        """异常场景1：Milvus 不可用时优雅降级"""
        # Mock pymilvus 不可用
        with patch.dict(os.environ, {"VECTOR_DB": "milvus"}, clear=True):
            with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus', side_effect=ImportError("pymilvus not available")):
                with pytest.raises(ImportError) as exc_info:
                    # 实例化 KnowledgeRetrieval
                    retrieval = KnowledgeRetrieval("test_milvus")
                    
                    # 验证优雅降级到 ChromaDB
                    assert retrieval.vector_db == "chromadb", "应该降级到 ChromaDB"
                    assert "pymilvus is not installed" in str(exc_info.value), "错误信息应包含 pymilvus 提示"
    
    def test_5_milvus_connection_failure_handling(self):
        """异常场景2：Milvus 连接失败时的处理"""
        # Mock pymilvus 可用但连接失败
        with patch.dict(os.environ, {"VECTOR_DB": "milvus"}, clear=True):
            with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus') as mock_pymilvus:
                with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.connections.connect') as mock_connect:
                    mock_connect.side_effect = Exception("Connection failed")
                    
                    with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.Collection') as mock_collection:
                        mock_collection.return_value = MagicMock()
                        
                        # 实例化 KnowledgeRetrieval
                        retrieval = KnowledgeRetrieval("test_milvus")
                        
                        # 验证连接失败时的处理
                        assert mock_connect.called, "应该尝试连接"
                        assert mock_collection.called, "应该尝试获取集合"
                        # 验证不会因为连接失败而崩溃
                        # 这里主要验证不会抛出未捕获的异常
                        
    def test_6_add_knowledge_chromadb(self):
        """正常场景4：向 ChromaDB 添加知识"""
        # Mock 环境变量，设置 VECTOR_DB=chromadb
        with patch.dict(os.environ, {"VECTOR_DB": "chromadb"}, clear=True):
            with patch('app.mcp_servers.knowledge_retrieval_server.chromadb.PersistentClient') as mock_chroma:
                with patch('app.mcp_servers.knowledge_retrieval_server.chromadb.PersistentClient.get_collection') as mock_get_collection:
                    with patch('app.mcp_servers.knowledge_retrieval_server.chromadb.PersistentClient.create_collection') as mock_create_collection:
                        with patch('app.mcp_servers.knowledge_retrieval_server.chromadb.PersistentClient.add') as mock_add:
                            # Mock 返回已存在的集合
                            mock_get_collection.return_value = MagicMock()
                            mock_add.return_value = None
                            
                            # 实例化 KnowledgeRetrieval
                            retrieval = KnowledgeRetrieval("test_chroma")
                            
                            # 调用 add_knowledge
                            result = retrieval.add_knowledge("测试内容", {"category": "test"}, "test_chroma")
                            
                            # 验证结果
                            assert result.startswith("Successfully added knowledge"), "添加成功"
                            assert mock_add.called, "应该调用 add 方法"
    
    def test_7_add_knowledge_milvus(self):
        """正常场景5：向 Milvus 添加知识"""
        # Mock pymilvus 可用
        with patch.dict(os.environ, {"VECTOR_DB": "milvus"}, clear=True):
            with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus') as mock_pymilvus:
                with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.connections.connect') as mock_connect:
                    with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.Collection') as mock_collection:
                        with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.Collection') as mock_collection_schema:
                            with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.CollectionSchema') as mock_field_schema:
                                with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.DataType') as mock_data_type:
                                    with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.utility') as mock_utility:
                                        # Mock 返回已存在的集合
                                        mock_collection.return_value = MagicMock()
                                        
                                        # 实例化 KnowledgeRetrieval
                                        retrieval = KnowledgeRetrieval("test_milvus")
                                        
                                        # 调用 add_knowledge
                                        result = retrieval.add_knowledge("测试内容", {"category": "test"}, "test_milvus")
                                        
                                        # 验证结果
                                        assert result.startswith("Successfully added knowledge"), "添加成功"
                                        assert mock_connect.called, "应该连接 Milvus"
                                        assert mock_collection.called, "应该获取集合"
    
    def test_8_search_knowledge_chromadb(self):
        """正常场景6：在 ChromaDB 中搜索知识"""
        # Mock 环境变量，设置 VECTOR_DB=chromadb
        with patch.dict(os.environ, {"VECTOR_DB": "chromadb"}, clear=True):
            with patch('app.mcp_servers.knowledge_retrieval_server.chromadb.PersistentClient') as mock_chroma:
                with patch('app.mcp_servers.knowledge_retrieval_server.chromadb.PersistentClient.get_collection') as mock_get_collection:
                    with patch('app.mcp_servers.knowledge_retrieval_server.chromadb.PersistentClient.create_collection') as mock_create_collection:
                        with patch('app.mcp_servers.knowledge_retrieval_server.chromadb.PersistentClient.add') as mock_add:
                            # Mock 返回已存在的集合
                            mock_get_collection.return_value = MagicMock()
                            mock_add.return_value = None
                            
                            # 实例化 KnowledgeRetrieval
                            retrieval = KnowledgeRetrieval("test_chroma")
                            
                            # 调用 search_knowledge
                            result = retrieval.search_knowledge("测试查询", "test_chroma")
                            
                            # 验证结果
                            assert isinstance(result, list), "应该返回列表"
                            assert len(result) > 0, "应该有搜索结果"
    
    def test_9_search_knowledge_milvus(self):
        """正常场景7：在 Milvus 中搜索知识"""
        # Mock pymilvus 可用
        with patch.dict(os.environ, {"VECTOR_DB": "milvus"}, clear=True):
            with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus') as mock_pymilvus:
                with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.connections.connect') as mock_connect:
                    with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.Collection') as mock_collection:
                        with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.Collection') as mock_collection_schema:
                            with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.CollectionSchema') as mock_field_schema:
                                with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.DataType') as mock_data_type:
                                    with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.utility') as mock_utility:
                                        # Mock 返回已存在的集合
                                        mock_collection.return_value = MagicMock()
                                        
                                        # 实例化 KnowledgeRetrieval
                                        retrieval = KnowledgeRetrieval("test_milvus")
                                        
                                        # 调用 search_knowledge
                                        result = retrieval.search_knowledge("测试查询", "test_milvus")
                                        
                                        # 验证结果
                                        assert isinstance(result, list), "应该返回列表"
                                        assert len(result) > 0, "应该有搜索结果"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
