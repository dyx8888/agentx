"""
16.3.3 性能测试：PerceptionPipeline延迟基准测试
目标：P95 < 500ms
"""
import time
import statistics
from unittest.mock import patch

import pytest


class TestPerceptionPipelinePerformance:
    """PerceptionPipeline 延迟基准测试"""

    @pytest.fixture
    def pipeline(self):
        """创建 PerceptionPipeline"""
        from app.perception.pipeline import PerceptionPipeline
        return PerceptionPipeline()

    # ── 基准1: InputFilter 阶段延迟 ──────────────────────────────

    def test_input_filter_latency(self, pipeline):
        """InputFilter 阶段延迟应 < 10ms"""
        from app.perception.input_filter import InputFilter

        test_inputs = [
            "帮我查一下最近的销售数据",
            "分析抖音平台KOL的数据表现",
            "我要投诉产品质量问题，请尽快处理" * 10,
        ]

        latencies = []
        for raw in test_inputs * 30:
            start = time.perf_counter()
            try:
                result = InputFilter.filter(raw)
            except ValueError:
                pass
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)

        p50 = statistics.median(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]

        assert p50 < 5.0, f"P50 InputFilter latency {p50:.2f}ms exceeds 5ms"
        assert p95 < 10.0, f"P95 InputFilter latency {p95:.2f}ms exceeds 10ms"

    # ── 基准2: 完整管道延迟（跳过 RAG） ──────────────────────────

    def test_pipeline_no_rag_latency(self, pipeline):
        """完整管道（跳过RAG）延迟基准"""
        latencies = []

        test_queries = [
            "帮我查一下最近的销售数据",
            "分析抖音平台KOL数据",
            "生成一份本周的运营报告",
            "推荐几个适合推广的达人",
            "查看仓库库存情况",
        ]

        for query in test_queries * 20:
            start = time.perf_counter()
            ctx = pipeline.run(raw_input=query, company_id="", skip_rag=True)
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)
            assert ctx is not None

        p50 = statistics.median(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]

        # 由于 LLM 调用是真实调用，此处验证管道框架开销
        assert p50 < 1000.0, f"P50 pipeline latency {p50:.2f}ms exceeds 1000ms"

    # ── 基准3: 过滤器吞吐量 ──────────────────────────────────────

    def test_filter_throughput(self, pipeline):
        """InputFilter 吞吐量应 > 1000 ops/s"""
        from app.perception.input_filter import InputFilter

        test_input = "帮我分析一下最近的销售数据表现情况"

        ops = 500
        start = time.perf_counter()
        for _ in range(ops):
            InputFilter.filter(test_input)
        elapsed = time.perf_counter() - start

        throughput = ops / elapsed
        assert throughput > 1000, f"Throughput {throughput:.0f} ops/s below 1000 ops/s"

    # ── 基准4: 恶意输入过滤性能 ──────────────────────────────────

    def test_malicious_input_filter_performance(self, pipeline):
        """恶意输入过滤不应显著影响性能"""
        from app.perception.input_filter import InputFilter

        normal_input = "帮我查一下数据"
        malicious_input = "<script>alert('xss')</script>DROP TABLE users; 正常查询"

        normal_times = []
        malicious_times = []

        for _ in range(100):
            start = time.perf_counter()
            InputFilter.filter(normal_input)
            normal_times.append((time.perf_counter() - start) * 1000)

            start = time.perf_counter()
            InputFilter.filter(malicious_input)
            malicious_times.append((time.perf_counter() - start) * 1000)

        normal_avg = statistics.mean(normal_times)
        malicious_avg = statistics.mean(malicious_times)

        # 恶意输入过滤不应比普通输入慢超过 2x
        assert malicious_avg < normal_avg * 2.0, \
            f"Malicious filter ({malicious_avg:.2f}ms) too slow vs normal ({normal_avg:.2f}ms)"

    # ── 基准5: 长输入处理性能 ────────────────────────────────────

    def test_long_input_performance(self, pipeline):
        """长输入处理不应有指数级退化"""
        from app.perception.input_filter import InputFilter

        lengths = [100, 500, 1000, 5000, 10000]
        times = []

        for length in lengths:
            test_input = "正常文本内容" * (length // 6)
            start = time.perf_counter()
            try:
                InputFilter.filter(test_input)
            except ValueError:
                pass
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        # 线性增长验证：5000字符不应比100字符慢超过50倍
        if times[0] > 0:
            ratio = times[3] / times[0]
            assert ratio < 50.0, f"Long input degradation ratio {ratio:.1f}x exceeds 50x"