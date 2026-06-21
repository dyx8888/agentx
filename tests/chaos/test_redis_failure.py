"""
16.4.1 混沌测试：Redis宕机降级
验证 Redis 不可用时各模块的降级行为
"""
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


class TestRedisFailureDegradation:
    """Redis 宕机降级混沌测试"""

    # ── 场景1: 幂等管理 Redis 宕机 → 降级本地缓存 ────────────────

    def test_idempotency_redis_down_fallback_local(self):
        """Redis 不可用时幂等管理器降级为本地缓存"""
        from app.core.idempotency import IdempotencyManager

        mgr = IdempotencyManager()
        # 断开 Redis 连接
        if mgr._connection_pool:
            mgr._connection_pool.disconnect()
        mgr._connected = False
        mgr._redis_client = None
        mgr._local_cache.clear()
        assert mgr.is_available is False, "Redis should be unavailable"

        # 基本操作仍应正常工作
        key = mgr.generate_key("c1", "a1", "t1", {"test": "fallback"})

        execution_count = [0]

        def side_effect_executor():
            execution_count[0] += 1
            return {"status": "ok", "via": "local_cache"}

        result, is_cached = mgr.check_or_execute(key, side_effect_executor)
        assert is_cached is False
        assert result["status"] == "ok"
        assert execution_count[0] == 1

        # 重复调用应命中本地缓存
        result2, is_cached2 = mgr.check_or_execute(key, side_effect_executor)
        assert is_cached2 is True
        assert execution_count[0] == 1, "Executor should not be called again"

        mgr.close()

    # ── 场景2: 幂等管理 Redis 连接失败 → 自动降级 ────────────────

    def test_idempotency_redis_connect_failure(self):
        """Redis 连接失败 → 自动降级到本地缓存，不抛异常"""
        from app.core.idempotency import IdempotencyManager

        # Mock _connect 方法使其失败
        with patch.object(IdempotencyManager, '_connect', return_value=False):
            mgr = IdempotencyManager()
            assert mgr.is_available is False

            # 功能仍可使用
            key = mgr.generate_key("c1", "a1", "t1", {"fallback": True})
            result, cached = mgr.check_or_execute(key, lambda: "fallback_ok")
            assert result == "fallback_ok"
            assert cached is False

            mgr.close()

    # ── 场景3: Checkpoint Redis 宕机 → 降级内存存储 ──────────────

    def test_checkpoint_redis_down_fallback_memory(self):
        """Redis 不可用时 checkpoint 降级为内存存储"""
        import app.core.checkpoint as cp_mod
        from unittest.mock import patch
        from collections import defaultdict

        with patch.object(cp_mod.RedisSaver, '__init__', lambda self, *args, **kwargs: None):
            saver = cp_mod.RedisSaver.__new__(cp_mod.RedisSaver)
            saver._connected = False
            saver._redis_client = None
            saver._connection_pool = None
            saver._storage = defaultdict(lambda: defaultdict(dict))
            saver._writes = defaultdict(dict)
            saver._blobs = {}
            saver._ttl = 3600
            saver.serde = None
        assert saver.is_available is False

        # 保存应降级到内存
        config = {"configurable": {"thread_id": "chaos_thread_1"}}
        checkpoint = {
            "id": "chaos_ckpt_1",
            "channel_versions": {"messages": "1"},
            "messages": [{"role": "user", "content": "chaos test"}],
            "plan": {"steps": []},
        }
        result_config = saver.put(config, checkpoint, {"step": 1}, {"messages": "1"})
        assert result_config is not None

        # 恢复应从内存获取
        restored = saver.get_tuple(config)
        assert restored is not None
        assert restored.checkpoint["id"] == "chaos_ckpt_1"

        saver.close()

    # ── 场景4: Redis 恢复后自动重连 ──────────────────────────────

    def test_redis_reconnect_on_retry(self):
        """Redis 恢复后应能自动重连"""
        from app.core.idempotency import IdempotencyManager

        # Mock _connect 第一次失败，第二次成功
        call_count = [0]

        def mock_connect(self):
            call_count[0] += 1
            if call_count[0] == 1:
                return False
            return True

        with patch.object(IdempotencyManager, '_connect', mock_connect):
            mgr = IdempotencyManager()
            assert mgr.is_available is False

            # 重试连接
            reconnected = mgr._connect()
            assert reconnected is True

            mgr.close()

    # ── 场景5: Redis 宕机后幂等操作不丢数据 ──────────────────────

    def test_no_data_loss_on_redis_failure(self):
        """Redis 宕机场景下本地缓存确保幂等不丢数据"""
        from app.core.idempotency import IdempotencyManager

        mgr = IdempotencyManager()
        if mgr._connection_pool:
            mgr._connection_pool.disconnect()
        mgr._connected = False
        mgr._redis_client = None
        mgr._local_cache.clear()

        # 正常运行时保存数据
        key = mgr.generate_key("c1", "a1", "t1", {"data": "important"})
        mgr.check_or_execute(key, lambda: {"critical": "data"}, ttl=60)

        # 仍应从本地缓存命中
        result = mgr.check_only(key)
        assert result is not None, "Local cache should still have data"
        assert result["critical"] == "data"

        mgr.close()

    # ── 场景6: Checkpoint Redis 宕机后 pending writes 不丢失 ─────

    def test_pending_writes_preserved_on_redis_failure(self):
        """Redis 宕机时 pending writes 保留在内存中"""
        import app.core.checkpoint as cp_mod
        from unittest.mock import patch
        from collections import defaultdict

        with patch.object(cp_mod.RedisSaver, '__init__', lambda self, *args, **kwargs: None):
            saver = cp_mod.RedisSaver.__new__(cp_mod.RedisSaver)
            saver._connected = False
            saver._redis_client = None
            saver._connection_pool = None
            saver._storage = defaultdict(lambda: defaultdict(dict))
            saver._writes = {}
            saver._blobs = {}
            saver._ttl = 3600
            saver.serde = None

        config = {"configurable": {"thread_id": "writes_chaos", "checkpoint_id": "ckpt_w"}}

        # 保存 checkpoint
        ckpt = {
            "id": "ckpt_w",
            "channel_versions": {"messages": "1"},
            "messages": [],
            "plan": {},
        }
        saver.put(config, ckpt, {}, {"messages": "1"})

        # 写入 pending writes
        writes = [("messages", {"role": "assistant", "content": "pending content"})]
        saver.put_writes(config, writes, task_id="task_chaos")

        # 恢复时 pending writes 应存在
        restored = saver.get_tuple(config)
        assert restored is not None
        assert len(restored.pending_writes) > 0

        saver.close()