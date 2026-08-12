"""
AgenticRAG 回归测试
验证「模式识别三问法」发现的问题及核心设计：
1. _get_hybrid 死代码已删除（无调用方）
2. FULL 策略分支保留并标注未启用
3. retrieve_structured 重复检索已修复（预检索 + _precomputed 复用，Milvus 查询减半）
4. 缓存三重保险（双检锁 + LRU + TTL）行为正确
5. 策略映射表 STRATEGY_MAP 角色回退正确
"""

import os
import sys
import threading

import pytest

sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import app.rag.agentic_rag as ar_module
from app.rag.agentic_rag import (
    AgenticRAG,
    RetrieveStrategy,
    clear_agentic_rag_cache,
    get_agentic_rag,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    """每个测试前后清空缓存，避免测试间污染"""
    clear_agentic_rag_cache()
    yield
    clear_agentic_rag_cache()


# ═══════════════════════════════════════════════════════════
# 策略映射表
# ═══════════════════════════════════════════════════════════
class TestGetStrategies:
    """STRATEGY_MAP 角色到策略的映射，未匹配回退 default"""

    def test_known_agent_returns_mapped_strategies(self):
        rag = AgenticRAG("test")
        assert rag.get_strategies("仓储物流") == [RetrieveStrategy.HYBRID]
        assert rag.get_strategies("客服专员") == [
            RetrieveStrategy.HYBRID,
            RetrieveStrategy.EXPERIENCE,
        ]

    def test_unknown_agent_falls_back_to_default(self):
        rag = AgenticRAG("test")
        strategies = rag.get_strategies("不存在的角色")
        assert strategies == ar_module.AgenticRAG.STRATEGY_MAP["default"]

    def test_default_has_hybrid_and_experience(self):
        """default 策略应包含 HYBRID 和 EXPERIENCE，保证基础检索能力"""
        rag = AgenticRAG("test")
        strategies = rag.get_strategies("default")
        assert RetrieveStrategy.HYBRID in strategies
        assert RetrieveStrategy.EXPERIENCE in strategies

    def test_no_role_uses_full_strategy(self):
        """FULL 策略当前未被任何角色启用（死代码分支的佐证）"""
        for role, strategies in AgenticRAG.STRATEGY_MAP.items():
            assert RetrieveStrategy.FULL not in strategies, (
                f"角色 {role} 启用了 FULL，但 FULL 分支标注为未启用"
            )


# ═══════════════════════════════════════════════════════════
# 缓存三重保险：双检锁 + LRU + TTL
# ═══════════════════════════════════════════════════════════
class TestCacheSingleton:
    """get_agentic_rag 单例：同公司同实例，不同公司不同实例"""

    def test_same_company_returns_same_instance(self):
        a = get_agentic_rag("co_1")
        b = get_agentic_rag("co_1")
        assert a is b

    def test_different_companies_different_instances(self):
        a = get_agentic_rag("co_1")
        b = get_agentic_rag("co_2")
        assert a is not b

    def test_concurrent_creation_thread_safe(self):
        """10 线程并发请求同一 company_id，应只产生一个实例"""
        instances = []
        barrier = threading.Barrier(10)

        def worker():
            barrier.wait()
            instances.append(get_agentic_rag("concurrent_co"))

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(instances) == 10
        assert all(i is instances[0] for i in instances), "并发创建不应产生多个 AgenticRAG 实例"


class TestCacheTTL:
    """TTL 过期后重建实例，拾取知识库更新"""

    def test_ttl_expiry_rebuilds_instance(self):
        """过期后再次获取，应返回新实例"""
        a = get_agentic_rag("co_ttl")
        # 手动把时间戳设为过期前，模拟 TTL 到期
        with ar_module._rag_cache_lock:
            old_ts, inst = ar_module._agentic_rag_cache["co_ttl"]
            ar_module._agentic_rag_cache["co_ttl"] = (
                old_ts - ar_module.CACHE_TTL_SECONDS - 1,
                inst,
            )
        b = get_agentic_rag("co_ttl")
        assert a is not b, "TTL 过期后应重建新实例"

    def test_ttl_within_window_returns_same_instance(self):
        """TTL 未过期时返回同一实例"""
        a = get_agentic_rag("co_fresh")
        b = get_agentic_rag("co_fresh")
        assert a is b


class TestCacheLRU:
    """LRU 策略：超过上限时淘汰最久未使用项"""

    def test_lru_evicts_oldest_when_exceeding_max(self):
        original_max = ar_module.MAX_CACHE_SIZE
        ar_module.MAX_CACHE_SIZE = 2  # 临时设小，方便测试
        try:
            get_agentic_rag("lru_1")
            get_agentic_rag("lru_2")
            get_agentic_rag("lru_3")  # 超过 2，淘汰 lru_1（最久未用）

            with ar_module._rag_cache_lock:
                assert "lru_1" not in ar_module._agentic_rag_cache
                assert "lru_2" in ar_module._agentic_rag_cache
                assert "lru_3" in ar_module._agentic_rag_cache
        finally:
            ar_module.MAX_CACHE_SIZE = original_max

    def test_lru_access_moves_to_end(self):
        """访问已有项会标记为最近使用，避免被淘汰"""
        original_max = ar_module.MAX_CACHE_SIZE
        ar_module.MAX_CACHE_SIZE = 2
        try:
            get_agentic_rag("a")
            get_agentic_rag("b")
            get_agentic_rag("a")  # 重新访问 a，a 变为最近使用
            get_agentic_rag("c")  # 超过 2，淘汰 b（最久未用）

            with ar_module._rag_cache_lock:
                assert "a" in ar_module._agentic_rag_cache
                assert "b" not in ar_module._agentic_rag_cache
                assert "c" in ar_module._agentic_rag_cache
        finally:
            ar_module.MAX_CACHE_SIZE = original_max


class TestClearCache:
    def test_clear_returns_count(self):
        get_agentic_rag("co_x")
        get_agentic_rag("co_y")
        cleared = clear_agentic_rag_cache()
        assert cleared == 2

    def test_clear_empties_cache(self):
        get_agentic_rag("co_z")
        clear_agentic_rag_cache()
        with ar_module._rag_cache_lock:
            assert len(ar_module._agentic_rag_cache) == 0


# ═══════════════════════════════════════════════════════════
# 死代码删除：_get_hybrid
# ═══════════════════════════════════════════════════════════
class TestDeadCodeRemoved:
    """_get_hybrid 已删除（零调用方的死代码）"""

    def test_get_hybrid_not_defined(self):
        """_get_hybrid 方法不应再存在于 AgenticRAG"""
        assert not hasattr(AgenticRAG, "_get_hybrid"), "_get_hybrid 是死代码，应已删除"

    def test_get_bus_still_exists(self):
        """_get_bus 仍存在（被 retrieve 使用）"""
        assert hasattr(AgenticRAG, "_get_bus")

    def test_get_graph_still_exists(self):
        """_get_graph 仍存在（被 retrieve 的 GRAPH 策略使用）"""
        assert hasattr(AgenticRAG, "_get_graph")


# ═══════════════════════════════════════════════════════════
# retrieve 流程：策略执行与拼接（mock bus/graph，不连 Milvus）
# ═══════════════════════════════════════════════════════════
class TestRetrieve:
    """retrieve 按策略映射调用对应检索源，并拼接结果"""

    def _make_rag_with_mock_bus(self, layer2="", layer3="", profile=None):
        """构造注入 mock bus 的 AgenticRAG"""
        rag = AgenticRAG("test_co")
        calls = {"layer2": 0, "layer3": 0, "graph": 0}

        class MockBus:
            def get_layer2_context(self, query, top_k=3, results=None):
                calls["layer2"] += 1
                return layer2

            def get_layer3_context(self, query, agent_name=None, top_k=3, results=None):
                calls["layer3"] += 1
                return layer3

            def get_profile(self):
                return profile

        rag._get_bus = lambda: MockBus()

        class MockGraph:
            def retrieve(self, query, depth=2):
                calls["graph"] += 1
                return ""

        rag._get_graph = lambda: MockGraph()
        return rag, calls

    def test_hybrid_only_role_calls_only_layer2(self):
        """仓储物流只有 HYBRID 策略，不应调 layer3 或 graph"""
        rag, calls = self._make_rag_with_mock_bus(layer2="知识库内容")
        result = rag.retrieve("查询", agent_name="仓储物流")

        assert "知识库内容" in result
        assert calls["layer2"] == 1
        assert calls["layer3"] == 0
        assert calls["graph"] == 0

    def test_experience_role_calls_layer2_and_layer3(self):
        """客服专员有 HYBRID + EXPERIENCE，应调 layer2 和 layer3"""
        rag, calls = self._make_rag_with_mock_bus(layer2="知识库", layer3="历史经验")
        result = rag.retrieve("查询", agent_name="客服专员")

        assert "知识库" in result
        assert "历史经验" in result
        assert calls["layer2"] == 1
        assert calls["layer3"] == 1

    def test_graph_disabled_by_param(self):
        """include_knowledge_graph=False 时跳过图谱检索"""
        rag, calls = self._make_rag_with_mock_bus(layer2="知识库")
        # 品牌商务有 GRAPH 策略，但传 include_knowledge_graph=False
        rag.retrieve("查询", agent_name="品牌商务", include_knowledge_graph=False)
        assert calls["graph"] == 0

    def test_empty_results_produce_empty_string(self):
        """所有检索源都无结果时，返回空字符串"""
        rag, _ = self._make_rag_with_mock_bus(layer2="", layer3="")
        result = rag.retrieve("查询", agent_name="仓储物流")
        assert result == ""

    def test_none_agent_uses_default_strategies(self):
        """agent_name=None 时使用 default 策略（HYBRID + EXPERIENCE）"""
        rag, calls = self._make_rag_with_mock_bus(layer2="L2", layer3="L3")
        rag.retrieve("查询", agent_name=None)
        assert calls["layer2"] == 1
        assert calls["layer3"] == 1  # default 含 EXPERIENCE


# ═══════════════════════════════════════════════════════════
# retrieve_structured 重复检索修复：预检索 + _precomputed 复用
# ═══════════════════════════════════════════════════════════
class TestRetrieveStructuredNoDuplicate:
    """retrieve_structured 应只检索知识库/经验各 1 次（修复前为各 2 次）"""

    def _make_rag_with_counting_bus(self, knowledge=None, experience=None, profile=None):
        """构造带调用计数的 mock bus，追踪 search_knowledge/search_experiences 调用次数"""
        rag = AgenticRAG("test_co")
        calls = {"search_knowledge": 0, "search_experiences": 0}

        class MockBus:
            def search_knowledge(self, query, top_k=5):
                calls["search_knowledge"] += 1
                return knowledge or []

            def search_experiences(self, query, agent_name=None, top_k=3):
                calls["search_experiences"] += 1
                return experience or []

            def get_layer2_context(self, query, top_k=3, results=None):
                # results 传入时应直接复用，不再调 search_knowledge
                if not results:
                    return ""
                return "\n【公司知识库相关内容】\n[来源1]\n" + results[0].get("content", "")

            def get_layer3_context(self, query, agent_name=None, top_k=3, results=None):
                if not results:
                    return ""
                return "\n【公司历史经验】\n1. [Agent] " + results[0].get("content", "")

            def get_profile(self):
                return profile

        rag._get_bus = lambda: MockBus()

        class MockGraph:
            def retrieve(self, query, depth=2):
                return ""

        rag._get_graph = lambda: MockGraph()
        return rag, calls

    def test_knowledge_searched_only_once(self):
        """retrieve_structured 中 search_knowledge 应只调用 1 次（修复前 2 次）"""
        rag, calls = self._make_rag_with_counting_bus(
            knowledge=[
                {
                    "content": "知识1",
                    "metadata": {},
                    "score": 0.9,
                    "source": "hybrid",
                    "source_file": "",
                    "chunk_index": 0,
                    "source_page": 0,
                }
            ],
            experience=[
                {
                    "content": "经验1",
                    "agent_name": "客服专员",
                    "task_type": "test",
                    "outcome": "成功",
                    "score": 0.8,
                }
            ],
        )
        rag.retrieve_structured("查询", agent_name="客服专员")
        assert calls["search_knowledge"] == 1, (
            f"知识库应只检索 1 次，实际 {calls['search_knowledge']} 次（重复检索未修复）"
        )

    def test_experience_searched_only_once(self):
        """retrieve_structured 中 search_experiences 应只调用 1 次（修复前 2 次）"""
        rag, calls = self._make_rag_with_counting_bus(
            knowledge=[
                {
                    "content": "知识1",
                    "metadata": {},
                    "score": 0.9,
                    "source": "hybrid",
                    "source_file": "",
                    "chunk_index": 0,
                    "source_page": 0,
                }
            ],
            experience=[
                {
                    "content": "经验1",
                    "agent_name": "客服专员",
                    "task_type": "test",
                    "outcome": "成功",
                    "score": 0.8,
                }
            ],
        )
        rag.retrieve_structured("查询", agent_name="客服专员")
        assert calls["search_experiences"] == 1, (
            f"经验应只检索 1 次，实际 {calls['search_experiences']} 次（重复检索未修复）"
        )

    def test_structured_result_contains_all_fields(self):
        """retrieve_structured 返回的 dict 应包含全部 4 个字段"""
        rag, _ = self._make_rag_with_counting_bus(
            knowledge=[
                {
                    "content": "知识1",
                    "metadata": {},
                    "score": 0.9,
                    "source": "hybrid",
                    "source_file": "",
                    "chunk_index": 0,
                    "source_page": 0,
                }
            ],
            experience=[
                {
                    "content": "经验1",
                    "agent_name": "客服专员",
                    "task_type": "test",
                    "outcome": "成功",
                    "score": 0.8,
                }
            ],
        )
        result = rag.retrieve_structured("查询", agent_name="客服专员")
        assert "context" in result
        assert "company_profile" in result
        assert "knowledge_results" in result
        assert "experience_results" in result
        assert len(result["knowledge_results"]) == 1
        assert len(result["experience_results"]) == 1

    def test_context_reuses_precomputed_knowledge(self):
        """context 文本应包含预检索的知识库内容（复用而非重新检索）"""
        rag, _ = self._make_rag_with_counting_bus(
            knowledge=[
                {
                    "content": "复用的知识",
                    "metadata": {},
                    "score": 0.9,
                    "source": "hybrid",
                    "source_file": "",
                    "chunk_index": 0,
                    "source_page": 0,
                }
            ],
            experience=[],
        )
        result = rag.retrieve_structured("查询", agent_name="仓储物流")
        assert "复用的知识" in result["context"]


# ═══════════════════════════════════════════════════════════
# retrieve 的 _precomputed 参数：复用预检索结果
# ═══════════════════════════════════════════════════════════
class TestRetrievePrecomputed:
    """retrieve 接受 _precomputed 参数，复用调用方预检索结果"""

    def test_precomputed_skips_internal_search(self):
        """传入 _precomputed 后，retrieve 内部不应再触发 search_knowledge"""
        rag = AgenticRAG("test_co")
        calls = {"search_knowledge": 0, "search_experiences": 0}
        pre = {
            "knowledge": [
                {
                    "content": "预检索知识",
                    "metadata": {},
                    "score": 0.9,
                    "source": "hybrid",
                    "source_file": "",
                    "chunk_index": 0,
                    "source_page": 0,
                }
            ],
            "experience": [],
        }

        class MockBus:
            def search_knowledge(self, query, top_k=5):
                calls["search_knowledge"] += 1
                return []

            def search_experiences(self, query, agent_name=None, top_k=3):
                calls["search_experiences"] += 1
                return []

            def get_layer2_context(self, query, top_k=3, results=None):
                if results:
                    return "\n【公司知识库相关内容】\n[来源1]\n" + results[0]["content"]
                return ""

            def get_layer3_context(self, query, agent_name=None, top_k=3, results=None):
                return ""

            def get_profile(self):
                return None

        rag._get_bus = lambda: MockBus()

        class MockGraph:
            def retrieve(self, query, depth=2):
                return ""

        rag._get_graph = lambda: MockGraph()

        result = rag.retrieve("查询", agent_name="仓储物流", _precomputed=pre)
        assert calls["search_knowledge"] == 0, "传入预检索结果后不应再调 search_knowledge"
        assert "预检索知识" in result

    def test_without_precomputed_still_works(self):
        """不传 _precomputed 时，retrieve 行为与原来一致（向后兼容）"""
        rag = AgenticRAG("test_co")

        class MockBus:
            def get_layer2_context(self, query, top_k=3, results=None):
                return "知识库内容"

            def get_layer3_context(self, query, agent_name=None, top_k=3, results=None):
                return "历史经验"

            def get_profile(self):
                return None

        rag._get_bus = lambda: MockBus()

        class MockGraph:
            def retrieve(self, query, depth=2):
                return ""

        rag._get_graph = lambda: MockGraph()

        result = rag.retrieve("查询", agent_name="客服专员")
        assert "知识库内容" in result
        assert "历史经验" in result
