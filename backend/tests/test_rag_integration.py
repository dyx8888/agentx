import pytest

from app.api.chat import _inject_rag_context
from app.rag.rag_prompt import build_rag_prompt, parse_citations


class TestRAGContextInjection:
    """验证 RAG 上下文注入到聊天消息"""

    def test_no_company_id_returns_original_message(self):
        message = "你好，请问有什么可以帮助你的？"
        result, refs = _inject_rag_context(message, "", "客服专员")
        assert result == message
        assert refs == []

    def test_none_company_id_returns_original_message(self):
        message = "测试消息"
        result, refs = _inject_rag_context(message, None, "品牌商务")
        assert result == message
        assert refs == []

    def test_injection_with_company_id_no_error(self):
        message = "我们公司的产品最近怎么样？"
        result, refs = _inject_rag_context(message, "1", "数据分析")
        assert message in result

    def test_injection_respects_agent_name(self):
        message = "帮我分析一下最近的销售数据"
        result_brand, _ = _inject_rag_context(message, "1", "品牌商务")
        result_warehouse, _ = _inject_rag_context(message, "1", "仓储物流")
        assert message in result_brand
        assert message in result_warehouse

    def test_rag_failure_returns_original_message(self, monkeypatch):
        def mock_retrieve(*args, **kwargs):
            raise RuntimeError("Simulated RAG failure")

        monkeypatch.setattr(
            "app.rag.agentic_rag.get_agentic_rag",
            lambda cid: type("MockRAG", (), {"retrieve": mock_retrieve})(),
        )
        message = "这条消息应该不变"
        result, refs = _inject_rag_context(message, "1", "客服专员")
        assert result == message
        assert refs == []


class TestRAGPrompt:
    """验证 RAG Prompt 模板"""

    def test_build_prompt_with_references(self):
        refs = [
            {"content": "产品A的月销售额为100万元", "source_file": "sales_report.pdf", "source_page": 3},
            {"content": "产品B的退货率为5%", "source_file": "quality_report.pdf", "source_page": 7},
        ]
        prompt = build_rag_prompt("本月的销售情况如何？", refs)
        assert "[来源1]" in prompt
        assert "[来源2]" in prompt
        assert "sales_report.pdf" in prompt
        assert "quality_report.pdf" in prompt
        assert "第3页" in prompt
        assert "第7页" in prompt
        assert "仅根据下方【参考资料】" in prompt
        assert "本月的销售情况如何？" in prompt

    def test_build_prompt_without_references(self):
        prompt = build_rag_prompt("测试问题", [])
        assert "当前知识库中没有与用户问题相关的资料" in prompt
        assert "测试问题" in prompt

    def test_build_prompt_no_source_file(self):
        refs = [{"content": "一些内容", "source_file": "", "source_page": 0}]
        prompt = build_rag_prompt("问题", refs)
        assert "[来源1]" in prompt
        assert "一些内容" in prompt

    def test_custom_system_instruction(self):
        refs = [{"content": "内容", "source_file": "doc.txt"}]
        prompt = build_rag_prompt("问题", refs, system_instruction="自定义指令")
        assert "自定义指令" in prompt
        assert "仅根据下方【参考资料】" not in prompt


class TestParseCitations:
    """验证引用解析"""

    def test_parse_single_citation(self):
        result = parse_citations("根据资料 [来源1] 显示，销售额增长。")
        assert result == [1]

    def test_parse_multiple_citations(self):
        text = "根据 [来源1] 和 [来源3] 的数据，同时参考 [来源1] 的结论。"
        result = parse_citations(text)
        assert result == [1, 3]

    def test_parse_no_citations(self):
        result = parse_citations("没有引用来源的回答。")
        assert result == []

    def test_parse_citations_sorted(self):
        text = "参考 [来源5]、[来源2] 和 [来源1]。"
        result = parse_citations(text)
        assert result == [1, 2, 5]