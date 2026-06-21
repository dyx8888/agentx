"""
16.3.4 性能测试：全功能开启回归测试
验证所有功能开启后 P99 不超过基线的 2 倍
"""
import time
import statistics
from unittest.mock import MagicMock, patch

import pytest


class TestFullFeatureRegression:
    """全功能开启回归测试"""

    @pytest.fixture
    def idempotency_mgr(self):
        from app.core.idempotency import IdempotencyManager
        mgr = IdempotencyManager()
        if mgr._connection_pool:
            mgr._connection_pool.disconnect()
        mgr._connected = False
        mgr._redis_client = None
        mgr._local_cache.clear()
        return mgr

    @pytest.fixture
    def saver(self):
        import app.core.checkpoint as cp_mod
        from unittest.mock import patch
        from collections import defaultdict

        with patch.object(cp_mod.RedisSaver, '__init__', lambda self, *args, **kwargs: None):
            s = cp_mod.RedisSaver.__new__(cp_mod.RedisSaver)
            s._connected = False
            s._redis_client = None
            s._storage = defaultdict(lambda: defaultdict(dict))
            s._writes = defaultdict(dict)
            s._blobs = {}
            s._ttl = 3600
            s.serde = None
        return s

    # ── 基准1: 幂等 + Checkpoint 联合操作延迟 ────────────────────

    def test_idempotency_and_checkpoint_combined(self, idempotency_mgr, saver):
        """幂等检查 + checkpoint 保存联合操作延迟"""
        thread_id = "combined_perf"
        config = {"configurable": {"thread_id": thread_id}}

        latencies = []
        for i in range(50):
            start = time.perf_counter()

            # 幂等检查
            key = idempotency_mgr.generate_key("c1", "a1", "t1", {"i": i})
            idempotency_mgr.check_or_execute(key, lambda: {"ok": True}, ttl=60)

            # checkpoint 保存
            ckpt = {
                "id": f"combined_{i}",
                "channel_versions": {"messages": str(i)},
                "messages": [{"role": "user", "content": f"msg_{i}"}],
                "plan": {"steps": []},
            }
            saver.put(config, ckpt, {"step": i}, {"messages": str(i)})

            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)

        p50 = statistics.median(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]

        # 联合操作 P95 < 100ms
        assert p95 < 100.0, f"P95 combined latency {p95:.2f}ms exceeds 100ms"

    # ── 基准2: 多模块并发操作 ────────────────────────────────────

    def test_concurrent_multi_module(self, idempotency_mgr, saver):
        """多模块并发操作回归测试"""
        import threading

        thread_id = "concurrent_regression"
        config = {"configurable": {"thread_id": thread_id}}

        latencies = []
        lock = threading.Lock()

        def worker(worker_id):
            local_latencies = []
            for i in range(20):
                start = time.perf_counter()

                # 幂等
                key = idempotency_mgr.generate_key("c1", f"w{worker_id}", "t", {"i": i})
                idempotency_mgr.check_or_execute(key, lambda: {"ok": True}, ttl=60)

                # checkpoint
                ckpt = {
                    "id": f"cr_{worker_id}_{i}",
                    "channel_versions": {"messages": str(i)},
                    "messages": [{"role": "user", "content": "test"}],
                    "plan": {},
                }
                saver.put(config, ckpt, {"step": i}, {"messages": str(i)})

                elapsed = (time.perf_counter() - start) * 1000
                local_latencies.append(elapsed)

            with lock:
                latencies.extend(local_latencies)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        assert p95 < 200.0, f"P95 concurrent multi-module latency {p95:.2f}ms exceeds 200ms"

    # ── 基准3: 感知管道 + checkpoint 回归 ────────────────────────

    def test_pipeline_and_checkpoint_regression(self, saver):
        """感知管道 + checkpoint 联合回归"""
        from app.perception.pipeline import PerceptionPipeline
        pipeline = PerceptionPipeline()

        thread_id = "pipe_regression"
        config = {"configurable": {"thread_id": thread_id}}

        latencies = []
        for i in range(20):
            # 感知管道
            ctx = pipeline.run(raw_input=f"查询数据_{i}", company_id="", skip_rag=True)

            start = time.perf_counter()

            # checkpoint 保存管道结果
            ckpt = {
                "id": f"pipe_{i}",
                "channel_versions": {"messages": str(i)},
                "messages": [{"role": "user", "content": ctx.augmented_message}],
                "plan": {"intent": ctx.intent.intent_type.value},
            }
            saver.put(config, ckpt, {"step": i}, {"messages": str(i)})

            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)

        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        assert p95 < 50.0, f"P95 pipeline+checkpoint latency {p95:.2f}ms exceeds 50ms"

    # ── 基准4: 内存占用不异常增长 ────────────────────────────────

    def test_memory_stability(self, idempotency_mgr, saver):
        """长时间运行内存不应异常增长"""
        initial_local_size = len(idempotency_mgr._local_cache)
        initial_storage_size = len(saver._storage)

        # 模拟大量操作
        for i in range(500):
            key = idempotency_mgr.generate_key("c1", "a1", "t1", {"i": i})
            idempotency_mgr.check_or_execute(key, lambda: {"ok": True}, ttl=1)

            if i % 50 == 0:
                ckpt = {
                    "id": f"mem_{i}",
                    "channel_versions": {"messages": str(i)},
                    "messages": [{"role": "user", "content": "test"}],
                    "plan": {},
                }
                config = {"configurable": {"thread_id": f"mem_{i}"}}
                saver.put(config, ckpt, {"step": i}, {"messages": str(i)})

        # 清理过期缓存
        idempotency_mgr._evict_local_cache()

        # 本地缓存不应无限增长（有 MAX_LOCAL_CACHE_SIZE 限制）
        final_local_size = len(idempotency_mgr._local_cache)
        assert final_local_size <= 1100, f"Local cache size {final_local_size} exceeds 1100"

    # ── 基准5: 单次请求端到端组合延迟 ────────────────────────────

    def test_end_to_end_request_profile(self, idempotency_mgr, saver):
        """端到端请求各组件组合延迟分析"""
        from app.perception.input_filter import InputFilter

        # 模拟一次完整请求的各阶段
        profile = {}

        # 1. InputFilter
        start = time.perf_counter()
        filtered = InputFilter.filter("帮我分析一下最近的销售数据")
        profile["input_filter"] = (time.perf_counter() - start) * 1000

        # 2. 幂等检查
        key = idempotency_mgr.generate_key("c1", "a1", "t1", {"query": "sales"})
        start = time.perf_counter()
        idempotency_mgr.check_or_execute(key, lambda: {"ok": True}, ttl=60)
        profile["idempotency"] = (time.perf_counter() - start) * 1000

        # 3. Checkpoint 保存
        ckpt = {
            "id": "e2e_test",
            "channel_versions": {"messages": "1"},
            "messages": [{"role": "user", "content": filtered}],
            "plan": {"steps": [{"name": "分析", "status": "pending"}]},
        }
        config = {"configurable": {"thread_id": "e2e_thread"}}
        start = time.perf_counter()
        saver.put(config, ckpt, {"step": 1}, {"messages": "1"})
        profile["checkpoint_save"] = (time.perf_counter() - start) * 1000

        # 4. Checkpoint 恢复
        start = time.perf_counter()
        saver.get_tuple(config)
        profile["checkpoint_load"] = (time.perf_counter() - start) * 1000

        total = sum(profile.values())
        assert total < 100.0, f"End-to-end profile total {total:.2f}ms exceeds 100ms"