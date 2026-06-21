"""
16.3.2 性能测试：Checkpoint保存延迟基准测试
目标：P95 < 50ms
"""
import time
import statistics
from unittest.mock import patch

import pytest


class TestCheckpointPerformance:
    """Checkpoint 保存/恢复性能基准测试"""

    @pytest.fixture
    def saver(self):
        """创建内存模式 RedisSaver"""
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

    def _make_checkpoint(self, thread_id, ckpt_id, msg_count=3):
        """创建测试 checkpoint"""
        return {
            "id": ckpt_id,
            "channel_versions": {"messages": str(msg_count)},
            "messages": [
                {"role": "user" if i % 2 == 0 else "assistant",
                 "content": f"message_{i}" * 50}
                for i in range(msg_count)
            ],
            "plan": {
                "steps": [
                    {"name": f"step_{j}", "status": "completed" if j < msg_count else "pending"}
                    for j in range(msg_count)
                ]
            },
        }

    # ── 基准1: 保存 checkpoint 延迟 ──────────────────────────────

    def test_save_latency(self, saver):
        """保存 checkpoint 延迟应 < 50ms P95"""
        latencies = []

        for i in range(100):
            thread_id = f"perf_save_{i}"
            config = {"configurable": {"thread_id": thread_id}}
            checkpoint = self._make_checkpoint(thread_id, f"ckpt_{i}", msg_count=5)

            start = time.perf_counter()
            saver.put(config, checkpoint, {"step": i}, {"messages": str(i)})
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)

        p50 = statistics.median(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]

        assert p50 < 30.0, f"P50 save latency {p50:.2f}ms exceeds 30ms"
        assert p95 < 50.0, f"P95 save latency {p95:.2f}ms exceeds 50ms"

    # ── 基准2: 恢复 checkpoint 延迟 ──────────────────────────────

    def test_load_latency(self, saver):
        """恢复 checkpoint 延迟应 < 20ms P95"""
        thread_id = "perf_load"
        config = {"configurable": {"thread_id": thread_id}}

        # 先保存一个 checkpoint
        checkpoint = self._make_checkpoint(thread_id, "ckpt_load", msg_count=10)
        saver.put(config, checkpoint, {"step": 0}, {"messages": "0"})

        latencies = []
        for _ in range(100):
            start = time.perf_counter()
            result = saver.get_tuple(config)
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)
            assert result is not None

        p50 = statistics.median(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]

        assert p50 < 10.0, f"P50 load latency {p50:.2f}ms exceeds 10ms"
        assert p95 < 20.0, f"P95 load latency {p95:.2f}ms exceeds 20ms"

    # ── 基准3: 大消息体 checkpoint 性能 ──────────────────────────

    def test_large_checkpoint_performance(self, saver):
        """大消息体 checkpoint 保存/恢复仍应在合理范围内"""
        thread_id = "perf_large"
        config = {"configurable": {"thread_id": thread_id}}

        large_checkpoint = {
            "id": "ckpt_large",
            "channel_versions": {"messages": "1"},
            "messages": [
                {"role": "user" if i % 2 == 0 else "assistant",
                 "content": "这是一段比较长的对话内容，用来模拟实际使用场景。" * 100}
                for i in range(20)
            ],
            "plan": {
                "steps": [{"name": f"step_{j}", "status": "pending"} for j in range(10)]
            },
        }

        # 保存性能
        start = time.perf_counter()
        saver.put(config, large_checkpoint, {"step": 0}, {"messages": "1"})
        save_time = (time.perf_counter() - start) * 1000

        # 恢复性能
        start = time.perf_counter()
        result = saver.get_tuple(config)
        load_time = (time.perf_counter() - start) * 1000

        assert result is not None
        assert save_time < 100.0, f"Large save latency {save_time:.2f}ms exceeds 100ms"
        assert load_time < 50.0, f"Large load latency {load_time:.2f}ms exceeds 50ms"

    # ── 基准4: 多次连续保存性能 ──────────────────────────────────

    def test_sequential_save_performance(self, saver):
        """连续保存多个 checkpoint 不应有性能退化"""
        thread_id = "perf_sequential"
        config = {"configurable": {"thread_id": thread_id}}

        batch_latencies = []
        for batch in range(5):
            batch_start = time.perf_counter()
            for i in range(20):
                ckpt = self._make_checkpoint(thread_id, f"ckpt_seq_{batch}_{i}", msg_count=5)
                saver.put(config, ckpt, {"step": batch * 20 + i}, {"messages": str(batch * 20 + i)})
            batch_time = (time.perf_counter() - batch_start) * 1000
            batch_latencies.append(batch_time / 20)  # 平均每次保存

        # 前5批和后5批的平均延迟不应有明显退化
        first_avg = sum(batch_latencies[:2]) / 2
        last_avg = sum(batch_latencies[-2:]) / 2
        # 退化不超过 2x
        assert last_avg < first_avg * 2.0, f"Performance degraded: {first_avg:.1f}ms -> {last_avg:.1f}ms"

    # ── 基准5: 删除 checkpoint 性能 ──────────────────────────────

    def test_delete_performance(self, saver):
        """删除 checkpoint 不应过慢"""
        thread_id = "perf_delete"
        config = {"configurable": {"thread_id": thread_id}}

        # 先创建多个 checkpoint
        for i in range(50):
            ckpt = self._make_checkpoint(thread_id, f"ckpt_del_{i}", msg_count=3)
            saver.put(config, ckpt, {"step": i}, {"messages": str(i)})

        start = time.perf_counter()
        saver.delete_thread(thread_id)
        elapsed = (time.perf_counter() - start) * 1000

        assert elapsed < 50.0, f"Delete latency {elapsed:.2f}ms exceeds 50ms"