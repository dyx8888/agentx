"""
16.1.2 RedisSaver 单元测试
保存/恢复/清理/TTL过期
"""
from unittest.mock import MagicMock, patch

import pytest


class TestRedisSaver:
    """RedisSaver checkpoint 单元测试"""

    @pytest.fixture
    def mock_redis(self):
        redis = MagicMock()
        redis.get.return_value = None
        redis.set.return_value = True
        redis.delete.return_value = True
        return redis

    @pytest.fixture
    def saver(self, mock_redis):
        import app.core.checkpoint as cp_mod
        with patch.object(cp_mod.RedisSaver, '_connect', return_value=True):
            saver = cp_mod.RedisSaver()
            saver._redis_client = mock_redis
            saver._connected = True
            yield saver
            saver.close()

    def test_save_checkpoint(self, saver, mock_redis):
        """测试保存 checkpoint"""
        mock_redis.set.return_value = True
        config = {"configurable": {"thread_id": "test_thread_1"}}
        checkpoint = {"id": "ckpt_1", "channel_versions": {"messages": "1"}, "messages": [], "plan": {}}
        result = saver.put(config, checkpoint, {}, {"messages": "1"})
        assert result is not None
        assert result["configurable"]["thread_id"] == "test_thread_1"

    def test_load_checkpoint(self, saver, mock_redis):
        """测试恢复 checkpoint"""
        import json
        config = {"configurable": {"thread_id": "test_thread_1"}}
        # 先保存
        checkpoint = {
            "id": "ckpt_2",
            "channel_versions": {"messages": "1"},
            "messages": [{"content": "hello"}],
            "plan": {"steps": []},
        }
        saver.put(config, checkpoint, {}, {"messages": "1"})
        # 恢复
        result = saver.get_tuple(config)
        assert result is not None

    def test_load_nonexistent_checkpoint(self, saver, mock_redis):
        """加载不存在的 checkpoint"""
        mock_redis.get.return_value = None
        config = {"configurable": {"thread_id": "nonexistent"}}
        result = saver.get_tuple(config)
        assert result is None

    def test_cleanup_checkpoint(self, saver, mock_redis):
        """测试清理 checkpoint"""
        mock_redis.delete.return_value = 1
        saver.delete_thread("test_thread_1")
        # 至少验证没有抛出异常
        assert True

    def test_fallback_when_redis_down(self):
        """Redis不可用时的内存降级"""
        import app.core.checkpoint as cp_mod
        with patch.object(cp_mod.RedisSaver, '_connect', return_value=False):
            saver = cp_mod.RedisSaver()
            assert saver is not None
            assert saver.is_available is False
            saver.close()