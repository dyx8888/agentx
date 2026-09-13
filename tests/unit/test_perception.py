"""
16.1.5 QueryRewriter 单元测试
补全/口语转结构化/空输入
"""

import pytest


class TestQueryRewriter:
    """查询改写器单元测试"""

    @pytest.fixture
    def rewriter(self):
        from app.perception.query_rewriter import QueryRewriter

        return QueryRewriter()

    def test_empty_input(self, rewriter):
        """空输入返回空"""
        assert rewriter.rewrite("") == ""
        # 空格-only 输入返回原始文本（或空）
        result = rewriter.rewrite("   ")
        assert result.strip() == ""

    def test_short_input_no_rewrite(self, rewriter):
        """短输入不触发改写"""
        result = rewriter.rewrite("你好")
        assert result == "你好"

    def test_normal_input_passthrough(self, rewriter):
        """正常输入（无LLM时）返回原文"""
        # 没有 model_gateway 时应该 fallback 到原文
        result = rewriter.rewrite("帮我查一下最近的销售数据")
        # 可能触发 LLM 异常，fallback 到原文
        assert isinstance(result, str)
        assert len(result) > 0

    def test_multiline_input(self, rewriter):
        """多行输入处理"""
        result = rewriter.rewrite("第一行\n第二行\n第三行")
        assert isinstance(result, str)

    def test_special_characters(self, rewriter):
        """特殊字符输入"""
        result = rewriter.rewrite("查询 @品牌A #活动 的 KOL 数据")
        assert isinstance(result, str)

    def test_raglive_query_skips_llm_even_when_enabled(self, monkeypatch):
        """明确知识库唯一标记查询不需要 LLM 改写"""
        from app.perception.query_rewriter import QueryRewriter

        class FailingGateway:
            def get_llm(self, company_id=None):
                raise AssertionError("LLM should not be called for direct knowledge query")

        monkeypatch.setenv("PERCEPTION_LLM_ENABLED", "true")
        text = "RAGLIVE-GMV-20260805 这条知识里 GMV 环比增长是多少？"

        assert QueryRewriter(model_gateway=FailingGateway()).rewrite(text) == text


class TestIntentExtractor:
    """意图提取器单元测试"""

    @pytest.fixture
    def extractor(self):
        from app.perception.intent_extractor import IntentExtractor

        return IntentExtractor()

    def test_empty_input(self, extractor):
        """空输入返回 GENERAL"""
        from app.perception.intent_extractor import IntentType

        intent = extractor.extract("")
        assert intent.intent_type == IntentType.GENERAL
        assert intent.confidence == 0.0

    def test_all_intent_types(self, extractor):
        """7种意图类型定义"""
        from app.perception.intent_extractor import IntentType

        types = [
            IntentType.SEARCH,
            IntentType.ANALYZE,
            IntentType.GENERATE,
            IntentType.DELEGATE,
            IntentType.MONITOR,
            IntentType.KNOWLEDGE,
            IntentType.GENERAL,
        ]
        assert len(types) == 7

    def test_malicious_detection(self, extractor):
        """恶意输入检测"""
        intent = extractor.extract("<script>alert('xss')</script>")
        # 无LLM时不应崩溃
        assert intent is not None
        assert isinstance(intent.is_malicious, bool)

    def test_intent_to_dict(self):
        """Intent 序列化"""
        from app.perception.intent_extractor import Intent, IntentType

        intent = Intent(
            intent_type=IntentType.SEARCH,
            confidence=0.9,
            entities={"platform": "douyin"},
        )
        d = intent.to_dict()
        assert d["intent_type"] == "search"
        assert d["confidence"] == 0.9
        assert d["entities"] == {"platform": "douyin"}

    def test_parse_invalid_json(self, extractor):
        """解析无效JSON"""
        result = extractor._parse_response("这不是JSON", "test query")
        from app.perception.intent_extractor import IntentType

        assert result.intent_type == IntentType.GENERAL
        assert result.confidence == 0.0

    def test_raglive_query_uses_heuristic_fast_path_even_when_llm_enabled(self, monkeypatch):
        """明确知识库唯一标记查询直接判为 knowledge，不等 LLM"""
        from app.perception.intent_extractor import IntentExtractor, IntentType

        class FailingGateway:
            def get_llm(self, company_id=None):
                raise AssertionError("LLM should not be called for direct knowledge query")

        monkeypatch.setenv("PERCEPTION_LLM_ENABLED", "true")
        text = "RAGLIVE-CS-20260805 里，敏感肌退换货要先确认什么？"

        intent = IntentExtractor(model_gateway=FailingGateway()).extract(text)

        assert intent.intent_type == IntentType.KNOWLEDGE
        assert intent.confidence >= 0.9
        assert intent.raw_response == "heuristic_direct_knowledge_query"

    def test_company_id_is_normalized_before_model_gateway_lookup(self):
        from app.perception.intent_extractor import _normalize_company_id

        assert _normalize_company_id("42") == 42
        assert _normalize_company_id(42) == 42
        assert _normalize_company_id("not-a-company") is None
