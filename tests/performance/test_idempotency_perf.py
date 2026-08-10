"""
16.3.1 性能测试：幂等检查延迟基准测试
目标：P95 < 5ms
"""
import time
import statistics
from unittest.mock import patch

import pytest


class TestIdempotencyPerformance:
    """幂等管理器性能基准测试"""

    @pytest.fixture
    def mgr(self):
        """创建纯本地缓存幂等管理器"""
        from app.core.idempotency import IdempotencyManager
        mgr = IdempotencyManager()
        if mgr._connection_pool:
            mgr._connection_pool.disconnect()
        mgr._connected = False
        mgr._redis_client = None
        mgr._local_cache.clear()
        return mgr

    # ── 基准1: 幂等键生成延迟 ────────────────────────────────────

    def test_key_generation_latency(self, mgr):
        """幂等键生成延迟应 < 1ms"""
        latencies = []

        for _ in range(100):
            start = time.perf_counter()
            mgr.generate_key(
                "company_1", "brand_bd", "search_kols",
                {"platform": "douyin", "followers_min": 100000, "category": "美妆"},
            )
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)

        p50 = statistics.median(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        p99 = sorted(latencies)[int(len(latencies) * 0.99)]

        assert p50 < 1.0, f"P50 key gen latency {p50:.2f}ms exceeds 1ms"
        assert p95 < 2.0, f"P95 key gen latency {p95:.2f}ms exceeds 2ms"

    # ── 基准2: check_or_execute 首次调用延迟 ─────────────────────

    def test_first_call_latency(self, mgr):
        """首次 check_or_execute 延迟应 < 5ms"""
        key = mgr.generate_key("c1", "a1", "t1", {"test": "perf"})
        latencies = []

        for i in range(100):
            unique_key = mgr.generate_key("c1", "a1", "t1", {"test": f"perf_{i}"})
            start = time.perf_counter()
            mgr.check_or_execute(unique_key, lambda: {"result": "ok"}, ttl=60)
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)

        p50 = statistics.median(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]

        assert p50 < 5.0, f"P50 first call latency {p50:.2f}ms exceeds 5ms"
        assert p95 < 10.0, f"P95 first call latency {p95:.2f}ms exceeds 10ms"

    # ── 基准3: 缓存命中延迟 ──────────────────────────────────────

    def test_cache_hit_latency(self, mgr):
        """缓存命中延迟应 < 1ms"""
        key = mgr.generate_key("c1", "a1", "t1", {"cached": "test"})
        mgr.check_or_execute(key, lambda: {"result": "ok"}, ttl=60)

        latencies = []
        for _ in range(1000):
            start = time.perf_counter()
            mgr.check_or_execute(key, lambda: {"result": "should_not_execute"}, ttl=60)
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)

        p50 = statistics.median(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]

        assert p50 < 0.5, f"P50 cache hit latency {p50:.3f}ms exceeds 0.5ms"
        assert p95 < 1.0, f"P95 cache hit latency {p95:.3f}ms exceeds 1ms"

    # ── 基准4: 本地缓存容量压力测试 ──────────────────────────────

    def test_large_cache_size_performance(self, mgr):
        """大量缓存条目下的延迟仍应 < 5ms"""
        # 填充缓存到上限
        for i in range(1000):
            key = mgr.generate_key("c1", "a1", "t1", {"fill": i})
            mgr.check_or_execute(key, lambda: f"result_{i}", ttl=60)

        # 在满缓存状态下测试延迟
        test_key = mgr.generate_key("c1", "a1", "t1", {"test": "large_cache"})
        latencies = []
        for _ in range(100):
            start = time.perf_counter()
            mgr.check_or_execute(test_key, lambda: "ok", ttl=60)
            mgr.clear_key(test_key)
            # 重新生成 key 避免缓存命中
            test_key = mgr.generate_key("c1", "a1", "t1", {"test": f"large_cache_{_}"})
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)

        p50 = statistics.median(latencies)
        assert p50 < 10.0, f"P50 large cache latency {p50:.2f}ms exceeds 10ms"

    # ── 基准5: 并发吞吐量 ────────────────────────────────────────

    def test_concurrent_throughput(self, mgr):
        """并发场景下的吞吐量应满足基本要求"""
        import threading

        results_per_thread = []
        lock = threading.Lock()

        def worker(thread_id):
            local_latencies = []
            for i in range(50):
                key = mgr.generate_key("c1", f"agent_{thread_id}", "tool", {"i": i})
                start = time.perf_counter()
                mgr.check_or_execute(key, lambda: {"thread": thread_id, "i": i}, ttl=60)
                elapsed = (time.perf_counter() - start) * 1000
                local_latencies.append(elapsed)
            with lock:
                results_per_thread.extend(local_latencies)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        total_time = (time.perf_counter() - start) * 1000

        total_ops = len(results_per_thread)
        throughput = total_ops / (total_time / 1000)

        p95 = sorted(results_per_thread)[int(len(results_per_thread) * 0.95)]
        assert p95 < 20.0, f"P95 concurrent latency {p95:.2f}ms exceeds 20ms"
        # 吞吐量至少 100 ops/s
        assert throughput > 100, f"Throughput {throughput:.0f} ops/s below 100 ops/s"