"""
EmbeddingService 回归测试
验证「模式识别三问法」发现的 3 个问题的修复：
1. Redis 缓存键包含 model_name，避免切换模型后命中旧向量（跨模型污染）
2. get_embedding_service 单例双重检查锁，线程安全
3. _run_async 用 get_running_loop 替代已弃用的 get_event_loop，精确异常捕获
"""

import asyncio
import os
import sys
import threading

import pytest

sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import app.rag.embedding_service as es_module
from app.rag.embedding_service import (
    EmbeddingAPIBackend,
    EmbeddingMode,
    _run_async,
    get_embedding_service,
)


@pytest.fixture(autouse=True)
def _reset_global_state():
    """每个测试前后清理模块级单例和后端注册表，避免测试间污染。

    _EMB_BACKEND_REGISTRY 是模块级 dict，EmbeddingAPIBackend.__init__ 会写入；
    _embedding_service 是模块级单例。两者都需要在测试间重置，
    否则前一个测试创建的实例会泄漏到后续测试，破坏隔离性。
    """
    yield
    es_module._EMB_BACKEND_REGISTRY.clear()
    es_module._embedding_service = None


# ═══════════════════════════════════════════════════════════
# 修复1：Redis 缓存键包含 model_name
# ═══════════════════════════════════════════════════════════
class TestRedisKeyIncludesModel:
    """Redis key 必须包含 model_name，否则切换模型后会命中旧向量。

    旧实现 key = "emb:{mode}:{md5}" 漏了 model_name：
    同一 mode 下从 bge-large 切到 bge-m3，Redis 仍返回 bge-large 的向量，
    维度相同但向量空间不同，导致 RAG 检索结果错乱。
    """

    def _make_backend(
        self, model_name="BAAI/bge-large-zh-v1.5", mode=EmbeddingMode.API_SILICONFLOW
    ):
        return EmbeddingAPIBackend(
            base_url="https://api.test.com/v1",
            api_key="sk-test",
            model_name=model_name,
            mode=mode,
        )

    def test_redis_key_format(self):
        """_redis_key 返回 emb:{mode}:{model_name}:{md5} 三段格式"""
        backend = self._make_backend()
        key = backend._redis_key("abc123")
        assert key == "emb:api_siliconflow:BAAI/bge-large-zh-v1.5:abc123"

    def test_different_models_produce_different_keys(self):
        """同 mode 不同 model 的 key 必须不同 —— 核心防污染断言"""
        b1 = self._make_backend(model_name="BAAI/bge-large-zh-v1.5")
        b2 = self._make_backend(model_name="BAAI/bge-m3")
        assert b1._redis_key("same_md5") != b2._redis_key("same_md5")

    def test_different_modes_produce_different_keys(self):
        """同 model 不同 mode 的 key 也应不同"""
        b1 = self._make_backend(mode=EmbeddingMode.API_SILICONFLOW)
        b2 = self._make_backend(mode=EmbeddingMode.API_OPENAI)
        assert b1._redis_key("same_md5") != b2._redis_key("same_md5")

    def test_redis_get_uses_model_in_key(self):
        """_redis_get 实际写入 Redis 的 key 包含 model_name"""
        backend = self._make_backend()
        captured = []

        class FakeRedis:
            def get(self, key):
                captured.append(key)
                return None

        backend._redis_client = FakeRedis()
        backend._redis_checked = True  # 跳过 _init_redis 的真连接
        backend._redis_get("deadbeef")
        assert captured, "_redis_get 应调用 client.get"
        assert "BAAI/bge-large-zh-v1.5" in captured[0]
        assert "deadbeef" in captured[0]

    def test_redis_set_uses_model_in_key(self):
        """_redis_set 实际写入 Redis 的 key 包含 model_name"""
        backend = self._make_backend()
        captured = []

        class FakeRedis:
            def setex(self, key, ttl, val):
                captured.append((key, ttl, val))

        backend._redis_client = FakeRedis()
        backend._redis_set("cafef00d", [0.1, 0.2])
        assert captured
        assert "BAAI/bge-large-zh-v1.5" in captured[0][0]
        assert captured[0][1] == backend.REDIS_TTL

    def test_no_cross_model_pollution_simulation(self):
        """端到端模拟：切换模型后，旧向量不应从 Redis 命中"""
        store = {}  # 模拟 Redis KV 存储

        class FakeRedis:
            def get(self, key):
                return store.get(key)

            def setex(self, key, ttl, val):
                store[key] = val

        # backend A：用 bge-large 写入"退货政策"的向量
        bA = self._make_backend(model_name="BAAI/bge-large-zh-v1.5")
        bA._redis_client = FakeRedis()
        bA._redis_checked = True
        bA._redis_set("md5_退货", [0.1] * 1024)  # bge-large 的向量

        # backend B：切换到 bge-m3，查询同一文本
        bB = self._make_backend(model_name="BAAI/bge-m3")
        bB._redis_client = FakeRedis()  # 共享同一个 store
        bB._redis_checked = True
        result = bB._redis_get("md5_退货")

        # 关键断言：bge-m3 不应命中 bge-large 写入的缓存
        assert result is None, "切换模型后不应命中旧模型的 Redis 缓存（跨模型污染）"


# ═══════════════════════════════════════════════════════════
# 修复2：get_embedding_service 单例双重检查锁
# ═══════════════════════════════════════════════════════════
class TestSingletonThreadSafety:
    """get_embedding_service 双重检查锁，线程安全。

    旧实现无锁 check-then-act：FastAPI 并发请求时多线程同时看到
    _embedding_service is None，各自创建实例，导致模型被重复加载。
    """

    def test_returns_same_instance(self):
        """多次调用返回同一实例"""
        es_module._embedding_service = None
        a = get_embedding_service()
        b = get_embedding_service()
        assert a is b

    def test_concurrent_creation_is_thread_safe(self):
        """10 线程并发创建，应只产生一个实例"""
        es_module._embedding_service = None
        instances = []
        barrier = threading.Barrier(10)

        def worker():
            barrier.wait()  # 同时放行，最大化竞态
            instances.append(get_embedding_service())

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(instances) == 10
        assert all(i is instances[0] for i in instances), (
            "并发创建不应产生多个 EmbeddingService 实例"
        )

    def test_concurrent_with_same_model_no_duplicate_init(self):
        """并发请求同一模型，实例唯一且模型名正确"""
        es_module._embedding_service = None
        results = []
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            svc = get_embedding_service("bge-small")
            results.append(svc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(r is results[0] for r in results)
        assert results[0]._raw_model_name == "bge-small"

    def test_switch_model_returns_same_instance(self):
        """切换模型时复用同一实例，不新建"""
        es_module._embedding_service = None
        s1 = get_embedding_service("bge-small")
        s2 = get_embedding_service("bge-base")
        assert s1 is s2
        assert s2._raw_model_name == "bge-base"

    def test_same_model_no_switch(self):
        """请求相同模型时不触发 switch_model（状态不被重置）"""
        es_module._embedding_service = None
        s1 = get_embedding_service("bge-small")
        s1._cache_hits = 999  # 篡改可观察字段
        s2 = get_embedding_service("bge-small")
        assert s2 is s1
        assert s2._cache_hits == 999, "相同模型不应触发 switch_model 重置状态"


# ═══════════════════════════════════════════════════════════
# 修复3：_run_async 用 get_running_loop
# ═══════════════════════════════════════════════════════════
class TestRunAsync:
    """_run_async 兼容 Python 3.12+，精确捕获无循环异常。

    旧实现用 asyncio.get_event_loop()（3.12+ 弃用），
    且 except RuntimeError: pass 包裹范围过大，会吞掉协程执行阶段的错误。
    """

    def test_no_running_loop_uses_asyncio_run(self):
        """无运行中的事件循环时，直接 asyncio.run 返回结果"""

        async def coro():
            return 42

        assert _run_async(coro()) == 42

    def test_in_running_loop_uses_thread_pool(self):
        """有运行中的事件循环时，借线程池执行，不抛 RuntimeError。

        模拟真实场景：async 路由内调用同步 encode() → _run_async。
        在新线程跑事件循环，避免与 pytest 主线程冲突。
        """
        result = []

        async def inner():
            async def coro():
                return 42

            r = _run_async(coro())  # 当前线程有运行中的循环
            result.append(r)

        def runner():
            asyncio.run(inner())

        t = threading.Thread(target=runner)
        t.start()
        t.join(timeout=10)

        assert result == [42], "嵌套循环场景应通过线程池正常返回"

    def test_coroutine_exception_propagates(self):
        """协程内部抛异常时，应向上传播而非被吞掉"""

        async def coro():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            _run_async(coro())

    def test_coroutine_runtimeerror_propagates(self):
        """协程内部抛 RuntimeError 时也应传播（旧实现会被 except 吞）"""

        async def coro():
            raise RuntimeError("inner error")

        with pytest.raises(RuntimeError, match="inner error"):
            _run_async(coro())


# ═══════════════════════════════════════════════════════════
# 向后兼容
# ═══════════════════════════════════════════════════════════
class TestBackwardCompatibility:
    def test_default_local_mode(self):
        """不传参数默认 LOCAL 模式（保留原行为）"""
        es_module._embedding_service = None
        svc = get_embedding_service()
        assert svc.mode == EmbeddingMode.LOCAL

    def test_encode_empty_returns_empty_array(self):
        """空输入返回空数组，不抛异常"""
        es_module._embedding_service = None
        svc = get_embedding_service()
        result = svc.encode([])
        assert len(result) == 0

    def test_cache_stats_structure(self):
        """cache_stats 返回结构包含必要字段"""
        es_module._embedding_service = None
        svc = get_embedding_service()
        stats = svc.cache_stats
        assert "hits" in stats
        assert "misses" in stats
        assert "mode" in stats
        assert stats["mode"] == "local"
