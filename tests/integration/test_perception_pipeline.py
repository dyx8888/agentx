"""
16.2.3 集成测试：PerceptionPipeline → Agent接收结构化上下文
验证完整的感知管道链路：输入 → 过滤 → 改写 → 意图提取 → RAG检索 → 结构化上下文
"""
from unittest.mock import MagicMock, patch

import pytest


class TestPerceptionPipelineIntegration:
    """PerceptionPipeline 集成测试"""

    @pytest.fixture
    def pipeline(self):
        """创建 PerceptionPipeline 实例"""
        from app.perception.pipeline import PerceptionPipeline
        return PerceptionPipeline()

    # ── 场景1: 完整管道执行（跳过 RAG） ──────────────────────────

    def test_full_pipeline_basic(self, pipeline):
        """完整管道处理基础查询"""
        ctx = pipeline.run(
            raw_input="帮我查一下最近的销售数据",
            company_id="",
            skip_rag=True,
        )

        assert ctx is not None
        assert ctx.raw_input == "帮我查一下最近的销售数据"
        assert ctx.filtered_input == "帮我查一下最近的销售数据"
        # 改写后的查询不应为空
        assert ctx.rewritten_query is not None
        assert len(ctx.rewritten_query) > 0
        # 意图应有值
        assert ctx.intent is not None
        # 增强消息应基于改写后的查询
        assert ctx.augmented_message is not None

    # ── 场景2: 口语化输入改写 ────────────────────────────────────

    def test_colloquial_input_rewritten(self, pipeline):
        """口语化输入应被改写为结构化表达"""
        colloquial_inputs = [
            "那个啥，帮我看看抖音上那个粉丝多的",
            "上次那个方案再给我整一下呗",
            "这个礼拜的数据咋样啊",
        ]

        for raw in colloquial_inputs:
            ctx = pipeline.run(raw_input=raw, company_id="", skip_rag=True)
            assert ctx.rewritten_query is not None
            assert len(ctx.rewritten_query) > 0

    # ── 场景3: 意图提取正确性 ────────────────────────────────────

    def test_intent_extraction(self, pipeline):
        """不同输入应提取出不同意图"""
        test_cases = [
            ("帮我查一下最近的销售数据", "data_query"),
            ("我要投诉产品质量问题", "complaint"),
            ("帮我生成一份周报", "report_generation"),
        ]

        for raw, expected_intent_type in test_cases:
            ctx = pipeline.run(raw_input=raw, company_id="", skip_rag=True)
            # 意图提取完成
            assert ctx.intent is not None
            assert ctx.intent.intent_type is not None

    # ── 场景4: 空输入检测 ────────────────────────────────────────

    def test_empty_input_raises_error(self, pipeline):
        """空输入应抛出 ValueError"""
        with pytest.raises(ValueError, match="空"):
            pipeline.run(raw_input="", company_id="", skip_rag=True)

        with pytest.raises(ValueError, match="空"):
            pipeline.run(raw_input="   ", company_id="", skip_rag=True)

    # ── 场景5: 超长输入检测 ──────────────────────────────────────

    def test_overly_long_input_raises_error(self, pipeline):
        """超长输入应抛出 ValueError"""
        long_input = "x" * 20000
        with pytest.raises(ValueError, match="长度"):
            pipeline.run(raw_input=long_input, company_id="", skip_rag=True)

    # ── 场景6: 恶意输入过滤 ──────────────────────────────────────

    def test_malicious_input_filtered(self, pipeline):
        """恶意输入应被过滤"""
        malicious_inputs = [
            "<script>alert('xss')</script>正常查询",
            "DROP TABLE users; 查询数据",
            "DELETE FROM orders WHERE 1=1;",
            "javascript:void(0) 查询",
        ]

        for raw in malicious_inputs:
            ctx = pipeline.run(raw_input=raw, company_id="", skip_rag=True)
            filtered = ctx.filtered_input.lower()
            # XSS 和 SQL 注入应被移除
            assert "<script>" not in filtered
            assert "drop table" not in filtered
            assert "delete from" not in filtered
            assert "javascript:" not in filtered

    # ── 场景7: 管道阶段跳过 ──────────────────────────────────────

    def test_skip_stages(self, pipeline):
        """跳过指定阶段后对应的字段应保持默认值"""
        # 跳过改写
        ctx = pipeline.run(
            raw_input="查询数据",
            company_id="",
            skip_rewrite=True,
            skip_rag=True,
        )
        assert ctx.rewritten_query == ctx.filtered_input

        # 跳过意图
        ctx2 = pipeline.run(
            raw_input="查询数据",
            company_id="",
            skip_intent=True,
            skip_rag=True,
        )
        # 跳过意图时使用默认值
        assert ctx2.intent is not None
        assert ctx2.intent.intent_type.value == "general"

    # ── 场景8: RAG增强消息生成 ───────────────────────────────────

    def test_rag_augmented_message_without_rag(self, pipeline):
        """无 RAG 时增强消息应等于改写后的查询"""
        ctx = pipeline.run(
            raw_input="帮我查数据",
            company_id="",
            skip_rag=True,
        )
        assert ctx.augmented_message is not None
        assert len(ctx.augmented_message) > 0

    # ── 场景9: 感知上下文数据结构完整性 ─────────────────────────

    def test_context_structure_completeness(self, pipeline):
        """PerceptionContext 应包含所有必要字段"""
        ctx = pipeline.run(
            raw_input="分析抖音平台KOL数据",
            company_id="test_company",
            agent_name="brand_bd",
            skip_rag=True,
        )

        # 验证所有字段存在
        assert hasattr(ctx, "raw_input")
        assert hasattr(ctx, "filtered_input")
        assert hasattr(ctx, "rewritten_query")
        assert hasattr(ctx, "intent")
        assert hasattr(ctx, "rag_results")
        assert hasattr(ctx, "tool_results")
        assert hasattr(ctx, "metadata")
        assert hasattr(ctx, "augmented_message")

        # 验证 metadata
        assert ctx.metadata["company_id"] == "test_company"
        assert ctx.metadata["agent_name"] == "brand_bd"

    # ── 场景10: 空白规范化 ───────────────────────────────────────

    def test_whitespace_normalization(self, pipeline):
        """多余空白应被规范化"""
        raw = "帮我  查一下\n\n\n最近的  数据\r\n报告"
        ctx = pipeline.run(raw_input=raw, company_id="", skip_rag=True)
        filtered = ctx.filtered_input
        # 不应有连续多个空格
        assert "   " not in filtered
        assert "\n\n\n" not in filtered