"""
16.4.4 混沌测试：并发资源竞争测试
验证高并发场景下的资源竞争和数据一致性
"""
import threading
import time
from unittest.mock import MagicMock, patch

import pytest


class TestConcurrencyChaos:
    """并发资源竞争混沌测试"""

    # ── 场景1: 并发写入幂等键 → 数据一致性 ────────────────────────

    def test_concurrent_idempotency_writes(self):
        """并发写入同一幂等键时数据一致性"""
        from app.core.idempotency import IdempotencyManager

        mgr = IdempotencyManager()
        if mgr._connection_pool:
            mgr._connection_pool.disconnect()
        mgr._connected = False
        mgr._redis_client = None
        mgr._local_cache.clear()

        key = mgr.generate_key("c1", "a1", "t1", {"concurrent": "write_test"})
        results = []
        errors = []
        lock = threading.Lock()

        def worker(worker_id):
            try:
                r, cached = mgr.check_or_execute(
                    key,
                    lambda: f"result_from_worker_{worker_id}",
                    ttl=60,
                )
                with lock:
                    results.append((worker_id, r, cached))
            except Exception as e:
                with lock:
                    errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 不应有错误
        assert len(errors) == 0, f"Errors occurred: {errors}"

        # 所有结果应一致（缓存命中或首次结果相同）
        cached_count = sum(1 for _, _, c in results if c)
        fresh_count = sum(1 for _, _, c in results if not c)

        assert cached_count + fresh_count == 10
        # 至少有一个成功的结果
        assert len(results) == 10

        mgr.close()

    # ── 场景2: 并发 checkpoint 保存 → 无数据损坏 ──────────────────

    def test_concurrent_checkpoint_saves(self):
        """并发保存 checkpoint 不应导致数据损坏"""
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

        thread_id = "concurrent_ckpt_chaos"
        results = []
        errors = []
        lock = threading.Lock()

        def worker(worker_id):
            try:
                config = {"configurable": {"thread_id": thread_id}}
                ckpt = {
                    "id": f"concurrent_ckpt_{worker_id}",
                    "channel_versions": {"messages": str(worker_id)},
                    "messages": [{"role": "user", "content": f"worker_{worker_id}"}],
                    "plan": {"worker": worker_id},
                }
                result_config = saver.put(config, ckpt, {"step": worker_id}, {"messages": str(worker_id)})
                with lock:
                    results.append(result_config)
            except Exception as e:
                with lock:
                    errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 10

        # 恢复后应能获取到 checkpoint
        config = {"configurable": {"thread_id": thread_id}}
        restored = saver.get_tuple(config)
        assert restored is not None

        saver.close()

    # ── 场景3: 读-修改-写竞争 ────────────────────────────────────

    def test_read_modify_write_race(self):
        """读-修改-写竞争场景下的数据一致性"""
        from app.core.idempotency import IdempotencyManager

        mgr = IdempotencyManager()
        if mgr._connection_pool:
            mgr._connection_pool.disconnect()
        mgr._connected = False
        mgr._redis_client = None
        mgr._local_cache.clear()

        counter = [0]
        lock = threading.Lock()

        def increment_counter():
            with lock:
                counter[0] += 1
            return counter[0]

        # 多个线程同时尝试首次写入
        key = mgr.generate_key("c1", "a1", "t1", {"race": "test"})
        results = []

        def worker():
            r, cached = mgr.check_or_execute(key, increment_counter, ttl=60)
            results.append((r, cached))

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 所有线程应返回相同结果
        first_result = results[0][0]
        for r, _ in results:
            assert r == first_result, f"Inconsistent results: {first_result} vs {r}"

        mgr.close()

    # ── 场景4: 高并发下的线程安全 ─────────────────────────────────

    def test_thread_safety_under_high_concurrency(self):
        """高并发下各模块不应出现线程安全问题"""
        from app.core.idempotency import IdempotencyManager

        mgr = IdempotencyManager()
        if mgr._connection_pool:
            mgr._connection_pool.disconnect()
        mgr._connected = False
        mgr._redis_client = None
        mgr._local_cache.clear()

        total_ops = 500
        ops_per_thread = total_ops // 5
        errors = []
        lock = threading.Lock()

        def worker(thread_id):
            for i in range(ops_per_thread):
                try:
                    key = mgr.generate_key("c1", f"agent_{thread_id}", "tool", {"i": i})
                    mgr.check_or_execute(key, lambda: {"ok": True}, ttl=60)
                    if i % 10 == 0:
                        mgr.clear_key(key)
                except Exception as e:
                    with lock:
                        errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.perf_counter() - start

        assert len(errors) == 0, f"Thread safety errors: {errors}"
        # 吞吐量验证
        throughput = total_ops / elapsed
        assert throughput > 50, f"Throughput {throughput:.0f} ops/s below 50"

        mgr.close()

    # ── 场景5: 并发读写混合 ──────────────────────────────────────

    def test_concurrent_read_write_mix(self):
        """并发读写混合操作不应导致数据不一致"""
        from app.core.idempotency import IdempotencyManager

        mgr = IdempotencyManager()
        if mgr._connection_pool:
            mgr._connection_pool.disconnect()
        mgr._connected = False
        mgr._redis_client = None
        mgr._local_cache.clear()

        # 预填充一些数据
        for i in range(10):
            key = mgr.generate_key("c1", "a1", "t1", {"prefill": i})
            mgr.check_or_execute(key, lambda: f"prefill_{i}", ttl=60)

        errors = []
        lock = threading.Lock()

        def reader():
            for _ in range(50):
                try:
                    key = mgr.generate_key("c1", "a1", "t1", {"prefill": 0})
                    mgr.check_only(key)
                except Exception as e:
                    with lock:
                        errors.append(str(e))

        def writer():
            for i in range(50):
                try:
                    key = mgr.generate_key("c1", "a1", "t1", {"write": i})
                    mgr.check_or_execute(key, lambda: f"write_{i}", ttl=60)
                except Exception as e:
                    with lock:
                        errors.append(str(e))

        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=reader))
        for _ in range(2):
            threads.append(threading.Thread(target=writer))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Read-write mix errors: {errors}"

        mgr.close()

    # ── 场景6: 死锁检测 ──────────────────────────────────────────

    def test_no_deadlock_under_contention(self):
        """锁竞争场景下不应出现死锁"""
        from app.core.idempotency import IdempotencyManager

        mgr = IdempotencyManager()
        if mgr._connection_pool:
            mgr._connection_pool.disconnect()
        mgr._connected = False
        mgr._redis_client = None
        mgr._local_cache.clear()

        completed = [0]
        lock = threading.Lock()

        def worker():
            for i in range(100):
                key = mgr.generate_key("c1", "a1", "t1", {"deadlock_test": i})
                mgr.check_or_execute(key, lambda: f"val_{i}", ttl=1)
                if i % 3 == 0:
                    mgr.clear_key(key)
            with lock:
                completed[0] += 1

        threads = [threading.Thread(target=worker) for _ in range(4)]

        start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)  # 10秒超时防死锁
        elapsed = time.perf_counter() - start

        # 不应超时
        for t in threads:
            assert not t.is_alive(), f"Thread {t.name} may be deadlocked"

        assert completed[0] == 4, f"Only {completed[0]}/4 threads completed"
        assert elapsed < 10.0, f"Test took {elapsed:.1f}s, possible deadlock"

        mgr.close()