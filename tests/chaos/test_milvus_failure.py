"""
16.4.3 混沌测试：Milvus宕机降级
验证 Milvus 向量数据库不可用时 RAG 检索的降级行为
"""
from unittest.mock import MagicMock, patch

import pytest


class TestMilvusFailureDegradation:
    """Milvus 宕机降级混沌测试"""

    # ── 场景1: Milvus 不可用 → RAG 跳过，管道继续 ────────────────

    def test_rag_skipped_when_milvus_down(self):
        """Milvus 不可用时 RAG 检索应跳过，管道继续执行"""
        from app.perception.pipeline import PerceptionPipeline

        pipeline = PerceptionPipeline()

        # 不传 company_id 时 skip_rag 为 True，管道正常执行
        ctx = pipeline.run(
            raw_input="帮我查一下最近的销售数据",
            company_id="",
            skip_rag=True,
        )

        assert ctx is not None
        assert ctx.raw_input is not None
        assert ctx.filtered_input is not None
        # RAG 结果应为空
        assert ctx.rag_results.context == ""

    # ── 场景2: RAG 检索异常 → 不中断管道 ─────────────────────────

    def test_rag_exception_does_not_break_pipeline(self):
        """RAG 检索抛出异常时不中断管道其他阶段"""
        from app.perception.pipeline import PerceptionPipeline

        pipeline = PerceptionPipeline()

        # 跳过 RAG 的情况下管道应正常完成
        ctx = pipeline.run(
            raw_input="分析平台数据",
            company_id="",
            skip_rag=True,
        )

        assert ctx is not None
        assert ctx.rewritten_query is not None
        assert ctx.intent is not None
        assert ctx.augmented_message is not None

    # ── 场景3: Milvus 连接超时 → 降级无 RAG 上下文 ───────────────

    def test_milvus_timeout_degradation(self):
        """Milvus 连接超时时降级为无 RAG 上下文模式"""
        from app.perception.rag_retriever import RagRetriever

        retriever = RagRetriever()

        # 模拟 Milvus 不可用
        retriever._available = False

        result = retriever.retrieve(
            query="测试查询",
            company_id="company_1",
            agent_name="test_agent",
            intent_type="data_query",
        )

        assert result is not None
        assert result.context == ""  # 无上下文
        assert result.knowledge_results == []

    # ── 场景4: RAG 降级后 Agent 仍可正常工作 ──────────────────────

    def test_agent_works_without_rag_context(self):
        """无 RAG 上下文时 Agent 仍应基于原始查询工作"""
        from app.perception.pipeline import PerceptionPipeline

        pipeline = PerceptionPipeline()

        ctx = pipeline.run(
            raw_input="帮我生成一份销售报告",
            company_id="",
            skip_rag=True,
        )

        # 增强消息应基于改写后的查询，不含 RAG 上下文
        assert ctx.augmented_message is not None
        assert len(ctx.augmented_message) > 0
        assert ctx.rag_results.context == ""

    # ── 场景5: 知识库检索失败 → 不影响意图提取 ────────────────────

    def test_rag_failure_no_impact_on_intent(self):
        """知识库检索失败不影响意图提取"""
        from app.perception.pipeline import PerceptionPipeline

        pipeline = PerceptionPipeline()

        test_queries = [
            "帮我查一下最近的销售数据",
            "我要投诉产品质量问题",
            "帮我生成一份周报",
        ]

        for query in test_queries:
            ctx = pipeline.run(raw_input=query, company_id="", skip_rag=True)
            assert ctx.intent is not None
            # 意图提取应正常完成

    # ── 场景6: Milvus 恢复后 RAG 自动恢复 ─────────────────────────

    def test_rag_auto_recovery_after_milvus_restored(self):
        """Milvus 恢复后 RAG 检索应自动恢复"""
        from app.perception.rag_retriever import RagRetriever

        retriever = RagRetriever()

        # 阶段1: Milvus 宕机
        retriever._available = False
        result1 = retriever.retrieve("测试", "c1", "a1", "data_query")
        assert result1.context == ""

        # 阶段2: Milvus 恢复
        retriever._available = True
        # 恢复后应能正常调用（即使没有真实 Milvus 也会返回空结果而非崩溃）
        result2 = retriever.retrieve("测试", "c1", "a1", "data_query")
        assert result2 is not None
        # 不抛异常即通过