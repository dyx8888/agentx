"""
向量数据库切换测试
测试 ChromaDB 和 Milvus 向量后端的切换和基本增删查功能
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.mcp_servers.knowledge_retrieval_server import KnowledgeRetrieval


class TestVectorBackend:
    """向量后端测试类"""

    def test_1_default_chromadb_success(self):
        """正常场景1：默认使用 ChromaDB"""
        with patch.dict(os.environ, {"VECTOR_DB": None}, clear=True):
            with patch('app.mcp_servers.knowledge_retrieval_server.chromadb.PersistentClient') as mock_chroma:
                with patch('app.mcp_servers.knowledge_retrieval_server.chromadb.PersistentClient.get_collection') as mock_get_collection:
                    with patch('app.mcp_servers.knowledge_retrieval_server.chromadb.PersistentClient.create_collection') as mock_create_collection:
                        mock_get_collection.return_value = None
                        mock_create_collection.return_value = MagicMock()

                        retrieval = KnowledgeRetrieval("test_chroma")

                        assert retrieval.vector_db == "chromadb"
                        assert mock_chroma.called
                        assert mock_get_collection.called
                        assert mock_create_collection.called

    def test_2_explicit_chromadb_success(self):
        """正常场景2：显式设置 ChromaDB"""
        with patch.dict(os.environ, {"VECTOR_DB": "chromadb"}, clear=True):
            with patch('app.mcp_servers.knowledge_retrieval_server.chromadb.PersistentClient') as mock_chroma:
                with patch('app.mcp_servers.knowledge_retrieval_server.chromadb.PersistentClient.get_collection') as mock_get_collection:
                    with patch('app.mcp_servers.knowledge_retrieval_server.chromadb.PersistentClient.create_collection') as mock_create_collection:
                        mock_get_collection.return_value = MagicMock()
                        mock_create_collection.return_value = MagicMock()

                        retrieval = KnowledgeRetrieval("test_chroma")

                        assert retrieval.vector_db == "chromadb"
                        assert mock_chroma.called
                        assert mock_get_collection.called
                        assert not mock_create_collection.called

    def test_3_milvus_unavailable_graceful_fallback(self):
        """异常场景1：Milvus 不可用时优雅降级"""
        with patch.dict(os.environ, {"VECTOR_DB": "milvus"}, clear=True):
            with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus', side_effect=ImportError("pymilvus not available")):
                with pytest.raises(ImportError) as exc_info:
                    retrieval = KnowledgeRetrieval("test_milvus")

                    assert retrieval.vector_db == "chromadb"
                    assert "pymilvus is not installed" in str(exc_info.value)

    def test_4_milvus_connection_failure_handling(self):
        """异常场景2：Milvus 连接失败时的处理"""
        with patch.dict(os.environ, {"VECTOR_DB": "milvus"}, clear=True):
            with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus') as mock_pymilvus:
                with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.connections.connect') as mock_connect:
                    mock_connect.side_effect = Exception("Connection failed")

                    with patch('app.mcp_servers.knowledge_retrieval_server.pymilvus.Collection') as mock_collection:
                        mock_collection.return_value = MagicMock()

                        retrieval = KnowledgeRetrieval("test_milvus")

                        assert mock_connect.called
                        assert mock_collection.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
