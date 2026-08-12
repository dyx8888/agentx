"""
16.1.1 IdempotencyManager 单元测试
幂等命中/未命中/Redis降级/TTL过期
"""

import time
import uuid

import pytest


class TestIdempotencyManager:
    """幂等管理器单元测试"""

    @pytest.fixture
    def manager(self, request):
        from app.core.idempotency import IdempotencyManager

        mgr = IdempotencyManager()
        mgr._local_cache = {}
        namespace = f"pytest-{request.node.name}-{uuid.uuid4().hex[:8]}"
        mgr._test_namespace = namespace
        original_generate_key = mgr.generate_key

        def generate_isolated_key(
            company_id,
            agent_name,
            tool_name,
            params,
            idempotency_key=None,
        ):
            return original_generate_key(
                f"{namespace}:{company_id}",
                agent_name,
                tool_name,
                params,
                idempotency_key=idempotency_key,
            )

        mgr.generate_key = generate_isolated_key
        yield mgr

        mgr.clear_namespace(namespace)
        mgr.close()

    def test_generate_key(self, manager):
        """测试幂等键生成"""
        key = manager.generate_key(
            "company_1", "brand_bd", "search_kols", {"platform": "douyin"}
        )
        assert "company_1" in key
        assert "brand_bd" in key
        assert "search_kols" in key

    def test_generate_key_deterministic(self, manager):
        """幂等键生成应具备确定性"""
        params = {"platform": "douyin", "followers_min": 100000}
        key1 = manager.generate_key("c1", "agent1", "tool1", params)
        key2 = manager.generate_key("c1", "agent1", "tool1", params)
        assert key1 == key2

    def test_generate_key_different_params(self, manager):
        """不同参数应生成不同键"""
        key1 = manager.generate_key("c1", "a1", "t1", {"p": "A"})
        key2 = manager.generate_key("c1", "a1", "t1", {"p": "B"})
        assert key1 != key2

    def test_check_or_execute_first_call(self, manager):
        """首次调用：未命中，执行成功"""
        key = manager.generate_key("c1", "a1", "t1", {})
        result, is_cached = manager.check_or_execute(key, lambda: "result_ok", ttl=60)
        assert is_cached is False
        assert result == "result_ok"

    def test_check_or_execute_duplicate(self, manager):
        """重复调用：命中缓存"""
        key = manager.generate_key("c1", "a1", "t1", {})
        manager.check_or_execute(key, lambda: "first_call", ttl=60)
        result, is_cached = manager.check_or_execute(key, lambda: "second_call", ttl=60)
        assert is_cached is True
        assert result == "first_call"

    def test_ttl_expiry(self, manager):
        """TTL过期后本地缓存应被清理"""
        key = manager.generate_key("c1", "a1", "t1", {})
        manager.check_or_execute(key, lambda: "expired_data", ttl=1)
        time.sleep(1.1)
        # 手动触发过期清理
        manager._evict_local_cache()
        result, is_cached = manager.check_or_execute(key, lambda: "new_data", ttl=1)
        assert is_cached is False
        assert result == "new_data"

    def test_local_fallback_when_redis_down(self, manager):
        """Redis不可用时应降级到本地缓存"""
        manager._connected = False
        manager._redis_client = None
        key = manager.generate_key("c1", "a1", "t1", {})
        result1, cached1 = manager.check_or_execute(key, lambda: "ok", ttl=60)
        assert cached1 is False
        result2, cached2 = manager.check_or_execute(
            key, lambda: "should_not_run", ttl=60
        )
        assert cached2 is True
        assert result2 == "ok"

    def test_check_only(self, manager):
        """check_only 测试：已有缓存时返回结果，无缓存时返回 None"""
        key = manager.generate_key("c1", "a1", "t1", {})
        assert manager.check_only(key) is None
        manager.check_or_execute(key, lambda: "stored", ttl=60)
        assert manager.check_only(key) == "stored"

    def test_clear_namespace_removes_isolated_keys(self, manager):
        key = manager.generate_key("c1", "a1", "namespace_test", {})
        manager.store(key, {"stored": True}, ttl=60)
        assert manager.check_only(key) == {"stored": True}

        removed = manager.clear_namespace(manager._test_namespace)

        assert removed >= 1
        assert manager.check_only(key) is None
