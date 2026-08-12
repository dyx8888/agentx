"""
PerceptionPipeline 回归测试
验证「模式识别三问法」发现的问题及修复：
1. _build_company_context 类型不匹配已修复（返回 dict，修复前返回 str 导致下游 .get() 崩溃）
2. _build_company_context 绕过单例工厂已修复（改为直接查库，与 chat._build_company_context_from_db 一致）
3. 异常处理细化（ValueError/TypeError 单独捕获）
4. PerceptionContext 数据类 field(default_factory) 行为正确
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.perception.intent_extractor import Intent
from app.perception.pipeline import PerceptionContext, PerceptionPipeline


# ═══════════════════════════════════════════════════════════
# _build_company_context 类型修复：返回 dict 而非 str
# ═══════════════════════════════════════════════════════════
class TestBuildCompanyContext:
    """_build_company_context 必须返回 dict（修复前返回 str，下游 .get() 会崩）"""

    def test_empty_company_id_returns_empty_dict(self):
        """无 company_id 时返回空 dict"""
        pipeline = PerceptionPipeline()
        assert pipeline._build_company_context("") == {}

    def test_returns_dict_not_str(self):
        """修复关键：返回值必须是 dict，不能是 str（修复前 get_context_for_agent 返回 str）"""
        pipeline = PerceptionPipeline()
        mock_company = MagicMock()
        mock_company.name = "测试公司"
        mock_company.brand_name = "测试品牌"
        mock_company.category = "电商"
        mock_company.platforms_json = '["taobao", "jd"]'

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_company
        mock_db = MagicMock()
        mock_db.get_session.return_value.__enter__.return_value = mock_session

        with patch("app.database.db", mock_db), patch("app.database.models.Company", MagicMock()):
            result = pipeline._build_company_context("1")

        assert isinstance(result, dict), f"应返回 dict，实际返回 {type(result).__name__}"
        assert not isinstance(result, str), "不能返回 str（会导致下游 .get() 崩溃）"

    def test_dict_has_expected_keys(self):
        """返回的 dict 应包含下游 build_system_message 期望的 4 个 key"""
        pipeline = PerceptionPipeline()
        mock_company = MagicMock()
        mock_company.name = "测试公司"
        mock_company.brand_name = "测试品牌"
        mock_company.category = "电商"
        mock_company.platforms_json = '["taobao"]'

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_company
        mock_db = MagicMock()
        mock_db.get_session.return_value.__enter__.return_value = mock_session

        with patch("app.database.db", mock_db), patch("app.database.models.Company", MagicMock()):
            result = pipeline._build_company_context("1")

        assert "company_name" in result
        assert "brand_name" in result
        assert "category" in result
        assert "platforms" in result
        assert result["company_name"] == "测试公司"
        assert result["brand_name"] == "测试品牌"
        assert result["category"] == "电商"
        assert result["platforms"] == ["taobao"]

    def test_platforms_json_empty_returns_empty_list(self):
        """platforms_json 为空时 platforms 返回空列表"""
        pipeline = PerceptionPipeline()
        mock_company = MagicMock()
        mock_company.name = "公司"
        mock_company.brand_name = ""
        mock_company.category = ""
        mock_company.platforms_json = None

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_company
        mock_db = MagicMock()
        mock_db.get_session.return_value.__enter__.return_value = mock_session

        with patch("app.database.db", mock_db), patch("app.database.models.Company", MagicMock()):
            result = pipeline._build_company_context("1")

        assert result["platforms"] == []

    def test_company_not_found_returns_empty_dict(self):
        """数据库中无此公司时返回空 dict"""
        pipeline = PerceptionPipeline()
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None
        mock_db = MagicMock()
        mock_db.get_session.return_value.__enter__.return_value = mock_session

        with patch("app.database.db", mock_db), patch("app.database.models.Company", MagicMock()):
            result = pipeline._build_company_context("999")

        assert result == {}

    def test_invalid_company_id_returns_empty_dict(self):
        """非数字 company_id（int 转换失败）应返回空 dict，不抛异常"""
        pipeline = PerceptionPipeline()
        result = pipeline._build_company_context("abc")
        assert result == {}

    def test_db_exception_returns_empty_dict(self):
        """数据库异常时返回空 dict，不阻塞主流程"""
        pipeline = PerceptionPipeline()
        mock_db = MagicMock()
        mock_db.get_session.side_effect = RuntimeError("DB down")

        with patch("app.database.db", mock_db):
            result = pipeline._build_company_context("1")

        assert result == {}

    def test_result_usable_with_get_method(self):
        """返回的 dict 必须支持 .get() 方法（修复前 str 无 .get 会 AttributeError）"""
        pipeline = PerceptionPipeline()
        mock_company = MagicMock()
        mock_company.name = "测试公司"
        mock_company.brand_name = "品牌"
        mock_company.category = "电商"
        mock_company.platforms_json = "[]"

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_company
        mock_db = MagicMock()
        mock_db.get_session.return_value.__enter__.return_value = mock_session

        with patch("app.database.db", mock_db), patch("app.database.models.Company", MagicMock()):
            result = pipeline._build_company_context("1")

        # 模拟下游 build_system_message 的访问方式
        assert result.get("company_name", "Unknown") == "测试公司"
        assert result.get("brand_name", "Unknown") == "品牌"
        assert result.get("category", "General") == "电商"
        assert result.get("platforms", []) == []


# ═══════════════════════════════════════════════════════════
# PerceptionContext 数据类
# ═══════════════════════════════════════════════════════════
class TestPerceptionContext:
    """PerceptionContext dataclass field(default_factory) 行为"""

    def test_default_lists_not_shared(self):
        """tool_results 列表不应在实例间共享"""
        c1 = PerceptionContext()
        c2 = PerceptionContext()
        c1.tool_results.append("x")
        assert c2.tool_results == [], "实例间 tool_results 列表不应共享"

    def test_default_metadata_not_shared(self):
        """metadata dict 不应在实例间共享"""
        c1 = PerceptionContext()
        c2 = PerceptionContext()
        c1.metadata["key"] = "val"
        assert c2.metadata == {}, "实例间 metadata dict 不应共享"

    def test_default_intent_not_shared(self):
        """intent 不应在实例间共享同一引用"""
        c1 = PerceptionContext()
        c2 = PerceptionContext()
        assert c1.intent is not c2.intent, "实例间 intent 不应共享同一引用"

    def test_raw_input_preserved(self):
        """raw_input 保留原始输入"""
        ctx = PerceptionContext(raw_input="原始输入")
        assert ctx.raw_input == "原始输入"


# ═══════════════════════════════════════════════════════════
# run 方法：skip 标志与异常处理
# ═══════════════════════════════════════════════════════════
class TestRunSkipFlags:
    """run 方法的 skip 标志控制各阶段执行"""

    def _make_pipeline_with_mocks(self):
        """构造所有子组件都 mock 的 pipeline，不依赖外部服务"""
        pipeline = PerceptionPipeline()
        pipeline._input_filter = MagicMock()
        pipeline._input_filter.filter.return_value = "过滤后的输入"
        pipeline._query_rewriter = MagicMock()
        pipeline._query_rewriter.rewrite.return_value = "改写后的查询"
        pipeline._intent_extractor = MagicMock()
        pipeline._intent_extractor.extract.return_value = Intent()
        pipeline._rag_retriever = MagicMock()
        pipeline._rag_retriever.retrieve.return_value = MagicMock(context="", references=[])
        pipeline._rag_retriever.augment_message.return_value = "增强消息"
        return pipeline

    def test_skip_rewrite_uses_filtered_input(self):
        """skip_rewrite=True 时，rewritten_query 等于 filtered_input"""
        pipeline = self._make_pipeline_with_mocks()
        ctx = pipeline.run("输入", skip_rewrite=True)
        assert ctx.rewritten_query == "过滤后的输入"
        pipeline._query_rewriter.rewrite.assert_not_called()

    def test_skip_intent_uses_default_intent(self):
        """skip_intent=True 时，使用默认 Intent"""
        pipeline = self._make_pipeline_with_mocks()
        ctx = pipeline.run("输入", skip_intent=True)
        assert isinstance(ctx.intent, Intent)
        pipeline._intent_extractor.extract.assert_not_called()

    def test_skip_rag_skips_retrieval(self):
        """skip_rag=True 时，不执行 RAG 检索"""
        pipeline = self._make_pipeline_with_mocks()
        pipeline.run("输入", company_id="1", skip_rag=True)
        pipeline._rag_retriever.retrieve.assert_not_called()

    def test_rag_skipped_without_company_id(self):
        """无 company_id 时自动跳过 RAG（检索无意义）"""
        pipeline = self._make_pipeline_with_mocks()
        pipeline.run("输入", company_id="")
        pipeline._rag_retriever.retrieve.assert_not_called()

    def test_value_error_propagates(self):
        """ValueError（输入验证失败）应直接向上抛"""
        pipeline = self._make_pipeline_with_mocks()
        pipeline._input_filter.filter.side_effect = ValueError("输入无效")
        with pytest.raises(ValueError, match="输入无效"):
            pipeline.run("输入")

    def test_metadata_records_call_params(self):
        """ctx.metadata 记录调用参数，供后续 Agent 判断"""
        pipeline = self._make_pipeline_with_mocks()
        ctx = pipeline.run("输入", company_id="42", agent_name="客服专员")
        assert ctx.metadata["company_id"] == "42"
        assert ctx.metadata["agent_name"] == "客服专员"
