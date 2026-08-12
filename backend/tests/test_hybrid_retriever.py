"""
HybridRetriever 回归测试
验证「模式识别三问法」发现的 4 个问题的修复：
1. RRF 融合：VectorRetriever 返回 doc_id，_rrf_fuse 按 doc_id 合并
   （旧实现用 vec_{rank} 做 key，与 BM25 的 doc_id 永远不一致，导致永不合并）
2. Milvus 表达式注入：_escape_milvus_expr 转义 company_id / doc_id
3. get_hybrid_retriever 单例双重检查锁，线程安全
4. index_documents 用 enumerate 替代 O(n²) 的 documents.index，并修复重复内容 ID 错乱
"""

import os
import sys
import threading

import numpy as np
import pytest

sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import app.rag.hybrid_retriever as hr_module
from app.rag.hybrid_retriever import (
    BM25Retriever,
    CrossEncoderReranker,
    HybridRetriever,
    get_hybrid_retriever,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    """每个测试前后清理模块级单例缓存，避免测试间污染"""
    yield
    hr_module._retriever_cache.clear()


class TestBM25Tokenizer:
    """BM25 should work for Chinese knowledge even without Milvus/vector search."""

    def test_chinese_query_matches_continuous_chinese_document(self):
        retriever = BM25Retriever()
        retriever.index(
            ["本品牌主推轻薄防晒衣，核心卖点是UPF50+、冰感透气。"],
            ["doc_1"],
        )

        results = retriever.search("防晒衣 UPF50 冰感", top_k=3)

        assert results
        assert results[0][0] == 0

    def test_english_space_tokenization_still_works(self):
        retriever = BM25Retriever()
        retriever.index(["refund policy delivery time"], ["doc_1"])

        results = retriever.search("refund delivery", top_k=3)

        assert results
        assert results[0][0] == 0


# ═══════════════════════════════════════════════════════════
# 修复2：Milvus 表达式注入防护
# ═══════════════════════════════════════════════════════════
class TestEscapeMilvusExpr:
    """_escape_milvus_expr 转义用户输入，防止表达式注入破坏多租户隔离"""

    def test_normal_string_unchanged(self):
        assert HybridRetriever._escape_milvus_expr("company_123") == "company_123"

    def test_escape_double_quote(self):
        """双引号被转义为 \""""
        assert HybridRetriever._escape_milvus_expr('a"b') == 'a\\"b'

    def test_escape_backslash(self):
        """反斜杠被转义为 \\"""
        assert HybridRetriever._escape_milvus_expr("a\\b") == "a\\\\b"

    def test_backslash_escaped_before_quote(self):
        """反斜杠先于双引号转义，避免引入新的转义序列"""
        # 输入 a\"b（反斜杠+双引号）：应输出 a\\\"b（反斜杠转义 + 双引号转义）
        assert HybridRetriever._escape_milvus_expr('a\\"b') == 'a\\\\\\"b'

    def test_injection_payload_neutralized(self):
        """注入 payload 被完全转义，无法破坏表达式结构"""
        payload = 'foo" or "1"=="1'
        escaped = HybridRetriever._escape_milvus_expr(payload)
        # 每个原始双引号都应被转义为 \"
        assert escaped.count('\\"') == payload.count('"')
        # 转义后构造的表达式：company_id 的值就是整个 payload 字符串字面量
        # Milvus 解析器不会把字面量内的 or 当作操作符
        expr = f'company_id == "{escaped}"'
        # 字面量内的 or 不会成为独立 token（前面没有未转义的引号闭合字面量）
        assert '\\" or \\"' in expr  # or 被包在转义引号内

    def test_non_string_coerced(self):
        """非字符串被强制转为字符串"""
        assert HybridRetriever._escape_milvus_expr(123) == "123"
        assert HybridRetriever._escape_milvus_expr(None) == "None"


# ═══════════════════════════════════════════════════════════
# 修复3：get_hybrid_retriever 单例双重检查锁
# ═══════════════════════════════════════════════════════════
class TestSingletonThreadSafety:
    """get_hybrid_retriever 双重检查锁，线程安全

    旧实现无锁 check-then-act：FastAPI 并发请求时多线程同时看到
    company_id 不在缓存，各自创建 HybridRetriever，重复连 Milvus / 加载模型。
    """

    def test_same_company_returns_same_instance(self):
        hr_module._retriever_cache.clear()
        a = get_hybrid_retriever("comp_1")
        b = get_hybrid_retriever("comp_1")
        assert a is b

    def test_different_companies_different_instances(self):
        hr_module._retriever_cache.clear()
        a = get_hybrid_retriever("comp_1")
        b = get_hybrid_retriever("comp_2")
        assert a is not b

    def test_concurrent_creation_thread_safe(self):
        """10 线程并发请求同一 company_id，应只产生一个实例"""
        hr_module._retriever_cache.clear()
        instances = []
        barrier = threading.Barrier(10)

        def worker():
            barrier.wait()
            instances.append(get_hybrid_retriever("concurrent_comp"))

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(instances) == 10
        assert all(i is instances[0] for i in instances), (
            "并发创建不应产生多个 HybridRetriever 实例"
        )

    def test_concurrent_different_companies_isolated(self):
        """不同 company 并发创建，各自独立且正确"""
        hr_module._retriever_cache.clear()
        results = {}
        lock = threading.Lock()
        barrier = threading.Barrier(4)

        def worker(cid):
            barrier.wait()
            inst = get_hybrid_retriever(cid)
            with lock:
                results[cid] = inst

        cids = ["a", "b", "c", "d"]
        threads = [threading.Thread(target=worker, args=(cid,)) for cid in cids]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert set(results.keys()) == set(cids)
        # 各 company 的实例应与再次获取的一致
        for c in cids:
            assert results[c] is get_hybrid_retriever(c)


# ═══════════════════════════════════════════════════════════
# 修复1：RRF 融合按 doc_id 合并
# ═══════════════════════════════════════════════════════════
class TestRRFFuse:
    """_rrf_fuse 用 doc_id 做 key 合并 BM25 和向量结果

    旧实现向量结果用 candidate_id = f"vec_{rank}"，与 BM25 的 doc_id
    格式永远不一致，导致：
    - source="hybrid" 永远不触发
    - 同一文档出现两条独立记录
    - RRF 分数无法累加
    """

    def _setup_retriever(self, docs):
        """构造已索引 BM25 的 HybridRetriever（不连 Milvus）"""
        retriever = HybridRetriever(company_id="test")
        retriever.bm25.index(
            [d["content"] for d in docs],
            [d["id"] for d in docs],
        )
        for d in docs:
            retriever._documents[d["id"]] = d
        return retriever

    def test_hybrid_merge_when_both_hit(self):
        """BM25 和向量命中同一 doc_id → source=hybrid，分数累加"""
        retriever = self._setup_retriever(
            [
                {"id": "doc_1", "content": "退货政策"},
                {"id": "doc_2", "content": "配送时效"},
            ]
        )
        bm25_results = [(0, 5.0), (1, 3.0)]  # doc_1 排名 0，doc_2 排名 1
        vector_results = [("doc_1", "退货政策", 0.9, "")]  # doc_1 也命中

        fused = retriever._rrf_fuse(bm25_results, vector_results, 0.3, 0.7)

        assert fused["doc_1"].source == "hybrid"
        assert fused["doc_1"].bm25_score == 5.0
        assert fused["doc_1"].vector_score == 0.9
        # 分数应累加（两路都是排名 0）
        rrf_k = 60
        expected = 0.3 * (1 / (rrf_k + 1)) + 0.7 * (1 / (rrf_k + 1))
        assert abs(fused["doc_1"].rrf_score - expected) < 1e-9

    def test_no_duplicate_records(self):
        """同一文档不应出现两条独立记录（旧 bug 的核心症状）"""
        retriever = self._setup_retriever([{"id": "doc_1", "content": "退货政策"}])
        bm25_results = [(0, 5.0)]
        vector_results = [("doc_1", "退货政策", 0.9, "")]

        fused = retriever._rrf_fuse(bm25_results, vector_results, 0.3, 0.7)

        assert len(fused) == 1, "同一文档应合并为一条记录，而非两条"
        assert fused["doc_1"].source == "hybrid"

    def test_bm25_only_and_vector_only(self):
        """单路命中的文档 source 正确标记"""
        retriever = self._setup_retriever(
            [
                {"id": "doc_1", "content": "退货政策"},
                {"id": "doc_2", "content": "配送时效"},
            ]
        )
        bm25_results = [(0, 5.0)]  # 仅 doc_1
        vector_results = [("doc_2", "配送时效", 0.9, "")]  # 仅 doc_2

        fused = retriever._rrf_fuse(bm25_results, vector_results, 0.3, 0.7)

        assert fused["doc_1"].source == "bm25"
        assert fused["doc_2"].source == "vector"

    def test_hybrid_score_higher_than_single(self):
        """hybrid 文档分数应高于单路命中（体现 RRF 累加的价值）"""
        retriever = self._setup_retriever(
            [
                {"id": "doc_1", "content": "退货政策"},
                {"id": "doc_2", "content": "配送"},
            ]
        )
        # doc_1：BM25 排名 0 + 向量排名 0（双路第一）
        # doc_2：仅向量排名 1
        bm25_results = [(0, 5.0)]
        vector_results = [("doc_1", "退货政策", 0.9, ""), ("doc_2", "配送", 0.8, "")]

        fused = retriever._rrf_fuse(bm25_results, vector_results, 0.3, 0.7)

        assert fused["doc_1"].source == "hybrid"
        assert fused["doc_2"].source == "vector"
        assert fused["doc_1"].rrf_score > fused["doc_2"].rrf_score

    def test_vector_doc_id_from_milvus_primary_key(self):
        """向量结果的 doc_id 来自 Milvus 主键，能正确与 BM25 合并"""
        retriever = self._setup_retriever([{"id": "doc_99", "content": "支付方式"}])
        # 模拟 VectorRetriever.search 返回 (doc_id, content, score, metadata)
        vector_results = [("doc_99", "支付方式", 0.85, '{"category": "pay"}')]
        bm25_results = [(0, 4.0)]

        fused = retriever._rrf_fuse(bm25_results, vector_results, 0.3, 0.7)

        assert "doc_99" in fused
        assert fused["doc_99"].source == "hybrid"
        # hybrid 合并时 metadata 由 BM25 先创建（这里为空），向量 metadata 不覆盖
        # 这是正常的合并优先级；纯向量命中的 metadata 解析见下一个测试

    def test_vector_only_metadata_parsed(self):
        """纯向量命中的 metadata 被正确 JSON 解析"""
        retriever = self._setup_retriever([{"id": "doc_1", "content": "退货政策"}])
        # doc_pay 不在 BM25 索引中，仅向量命中
        vector_results = [("doc_pay", "支付方式", 0.85, '{"category": "pay"}')]
        bm25_results = []

        fused = retriever._rrf_fuse(bm25_results, vector_results, 0.3, 0.7)

        assert fused["doc_pay"].source == "vector"
        assert fused["doc_pay"].metadata.get("category") == "pay"


# ═══════════════════════════════════════════════════════════
# 修复4：index_documents 用 enumerate
# ═══════════════════════════════════════════════════════════
class TestIndexDocumentsEnumerate:
    """index_documents 用 enumerate 替代 documents.index

    旧实现 documents.index(d) 在循环内调用，O(n²)；
    且 list.index 用值相等，重复内容文档会返回第一个索引，导致 ID 错乱。
    """

    def _make_retriever_no_milvus(self):
        """构造跳过 Milvus 连接的 HybridRetriever"""
        retriever = HybridRetriever(company_id="test")
        # 跳过 Milvus 初始化和写入
        retriever.vector._initialized = True
        retriever.vector._collection = None

        # mock embedding 服务，返回零向量，避免加载真模型
        class MockEmb:
            def encode(self, texts):
                return np.zeros((len(texts), 512))

            def encode_single(self, text):
                return np.zeros(512)

        retriever._embedding_service = MockEmb()
        return retriever

    def test_duplicate_content_doc_ids_correct(self):
        """重复内容文档的 ID 不再错乱（旧 bug 的核心症状）"""
        retriever = self._make_retriever_no_milvus()
        docs = [
            {"id": "doc_1", "content": "相同内容"},
            {"id": "doc_2", "content": "相同内容"},  # 与 doc_1 内容完全相同
            {"id": "doc_3", "content": "不同内容"},
        ]
        retriever.index_documents(docs)

        # 三篇文档都应正确存入，ID 与内容一一对应
        assert set(retriever._documents.keys()) == {"doc_1", "doc_2", "doc_3"}
        assert retriever._documents["doc_1"]["content"] == "相同内容"
        assert retriever._documents["doc_2"]["content"] == "相同内容"
        assert retriever._documents["doc_3"]["content"] == "不同内容"

    def test_auto_generated_ids_use_enumerate_index(self):
        """未提供 id 时，自动生成的 ID 用 enumerate 索引（而非 index 返回值）"""
        retriever = self._make_retriever_no_milvus()
        docs = [
            {"content": "文档A"},
            {"content": "文档B"},
            {"content": "文档A"},  # 与文档A 内容相同
        ]
        retriever.index_documents(docs)

        # 三篇文档都应存入，自动 ID 为 "0", "1", "2"
        assert "0" in retriever._documents
        assert "1" in retriever._documents
        assert "2" in retriever._documents
        # 旧 bug：第三篇的 ID 会被错赋成 "0"（index 返回第一个匹配），导致第三篇丢失
        assert retriever._documents["2"]["content"] == "文档A"

    def test_bm25_index_built_correctly(self):
        """index_documents 后 BM25 索引可用"""
        retriever = self._make_retriever_no_milvus()
        retriever.index_documents(
            [
                {"id": "d1", "content": "退货 退款"},
                {"id": "d2", "content": "配送 物流"},
            ]
        )
        assert retriever._indexed is True
        # BM25 能检索到
        results = retriever.bm25.search("退货", top_k=2)
        assert len(results) > 0
        assert retriever.bm25._doc_ids[results[0][0]] == "d1"


# ═══════════════════════════════════════════════════════════
# BM25 基础功能（纯内存，验证未破坏原逻辑）
# ═══════════════════════════════════════════════════════════
class TestBM25Retriever:
    def test_index_and_search(self):
        bm = BM25Retriever()
        bm.index(["退货政策 退款", "配送时效 物流", "支付方式"])
        results = bm.search("退货 退款", top_k=2)
        assert len(results) > 0
        assert results[0][0] == 0  # 第一篇文档最相关

    def test_no_match_returns_empty(self):
        bm = BM25Retriever()
        bm.index(["退货政策"])
        results = bm.search("不存在的词xyz", top_k=5)
        assert results == []

    def test_custom_doc_ids(self):
        bm = BM25Retriever()
        bm.index(["退货 政策"], ["doc_abc"])  # 空格分词，查询词需匹配分词后 token
        results = bm.search("退货", top_k=1)
        assert results[0][0] == 0
        assert bm._doc_ids[0] == "doc_abc"


class TestCrossEncoderReranker:
    def test_load_failure_keeps_original_order(self, monkeypatch):
        """精排模型不可用时应降级保留候选结果，而不是让整次搜索失败。"""
        real_import = __import__

        class BrokenCrossEncoder:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("offline model cache miss")

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "sentence_transformers":
                return type("SentenceTransformersModule", (), {"CrossEncoder": BrokenCrossEncoder})
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr("builtins.__import__", fake_import)
        reranker = CrossEncoderReranker(model_name="missing-reranker")

        assert reranker.rerank("query", ["doc a", "doc b"], top_k=2) == [(0, 0.0), (1, 0.0)]
        assert reranker._load_failed is True


class TestVectorRetrieverBackoff:
    def test_client_search_result_format(self):
        results = hr_module.VectorRetriever._format_client_search_results(
            [
                [
                    {
                        "id": "doc_1",
                        "distance": 0.91,
                        "entity": {
                            "content": "退货政策",
                            "metadata": '{"category":"policy"}',
                        },
                    }
                ]
            ]
        )

        assert results == [("doc_1", "退货政策", 0.91, '{"category":"policy"}')]

    def test_failed_init_is_not_retried_immediately(self, monkeypatch):
        calls = []
        real_import = __import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "pymilvus":
                calls.append(name)
                raise ImportError("pymilvus unavailable")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr("builtins.__import__", fake_import)
        retriever = hr_module.VectorRetriever()
        retriever._retry_interval = 60

        retriever._ensure_initialized()
        retriever._ensure_initialized()

        assert calls == ["pymilvus"]
        assert retriever._collection is None
        assert retriever._initialized is False
