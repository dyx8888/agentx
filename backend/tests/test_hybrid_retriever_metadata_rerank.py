import os
import sys

sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.rag import hybrid_retriever as hybrid_module
from app.rag.hybrid_retriever import (
    HybridRetriever,
    SearchResult,
    _is_fact_line_for_domain,
    _is_medical_evidence_content_fact_line,
    _metadata_boost_score,
)


class _VectorDocs:
    def __init__(self, rows=None, exc: Exception | None = None):
        self.rows = rows or []
        self.exc = exc
        self.calls = 0

    def search(self, query_vector, top_k=10):
        return []

    def list_documents(self):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.rows


class _EmbeddingService:
    def encode_single(self, query):
        return [0.0]


def _result(
    content: str,
    *,
    score: float,
    source_file: str = "",
    chunk_type: str | None = None,
    fact_ids: list[str] | None = None,
    markers: list[str] | None = None,
    section_title: str = "",
) -> SearchResult:
    metadata = {}
    if source_file:
        metadata["source_file"] = source_file
    if chunk_type:
        metadata["chunk_type"] = chunk_type
    if fact_ids is not None:
        metadata["fact_ids"] = fact_ids
    if markers is not None:
        metadata["markers"] = markers
    if section_title:
        metadata["section_title"] = section_title
    return SearchResult(
        content=content,
        metadata=metadata,
        rrf_score=score,
        source_file=source_file,
    )


def test_q027_like_query_promotes_service_and_content_evidence_into_top5():
    query = "资料里是否允许客服诊断用户皮肤疾病？"
    candidates = [
        _result("inventory replacement", score=0.0167, source_file="qpack_02_inventory_fulfillment.txt", chunk_type="fact_line", fact_ids=["F_INV_006"], markers=["QPACK_INV_EAST_006"]),
        _result("platform allowed expression", score=0.0166, source_file="qpack_06_platform_rules.txt", chunk_type="fact_line", fact_ids=["F_RULE_002"], markers=["QPACK_RULE_002"]),
        _result("promo target", score=0.0165, source_file="qpack_04_promo_818.txt", chunk_type="fact_line", fact_ids=["F_PROMO_006"], markers=["QPACK_PROMO_818_006"]),
        _result("inventory update", score=0.0164, source_file="qpack_09_conflict_update_notice.txt", chunk_type="update_notice", fact_ids=["F_UPDATE_003"], markers=["QPACK_UPDATE_003"]),
        _result("report noise", score=0.0163, source_file="qpack_08_ops_weekly_report.txt", chunk_type="fact_line", fact_ids=["F_REPORT_007"], markers=["QPACK_REPORT_007"]),
        _result("fact_id=F_SERVICE_002 | marker=QPACK_SERVICE_002 | 过敏反馈不得诊断疾病", score=0.0150, source_file="qpack_05_after_sales_sop.txt", chunk_type="fact_line", fact_ids=["F_SERVICE_002"], markers=["QPACK_SERVICE_002"]),
        _result("fact_id=F_CONTENT_007 | marker=QPACK_CONTENT_007 | 评论区不得给医疗建议", score=0.0149, source_file="qpack_07_content_script_rules.txt", chunk_type="fact_line", fact_ids=["F_CONTENT_007"], markers=["QPACK_CONTENT_007"]),
    ]

    reranked = HybridRetriever._apply_metadata_boost(query, candidates, top_k=5)
    joined = "\n".join(result.content for result in reranked)

    assert "F_SERVICE_002" in joined
    assert "F_CONTENT_007" in joined


def test_absence_query_keeps_synthetic_disclaimer_evidence():
    query = "资料里是否给出了真实达人账号链接？"
    disclaimer = _result(
        "本文件为 public-demo synthetic 测试资料，不对应任何真实商家或个人。",
        score=0.015,
        source_file="qpack_03_kol_matrix.txt",
        chunk_type="paragraph",
    )
    noise = _result("unstructured noise", score=0.015)

    assert _metadata_boost_score(query, disclaimer) > 0
    assert _metadata_boost_score("组合装A当前库存是多少？", disclaimer) < 0
    assert HybridRetriever._apply_metadata_boost(query, [noise, disclaimer], top_k=1) == [
        disclaimer
    ]


def test_multi_file_query_keeps_relevant_service_and_content_sources():
    query = "如果用户问敏感肌能不能用，应结合商品手册和客服SOP怎么回答？"
    candidates = [
        _result("product applicability", score=0.0200, source_file="qpack_01_product_manual.txt", chunk_type="fact_line", fact_ids=["F_PRODUCT_004"], markers=["QPACK_PRODUCT_SERUM_004"]),
        _result("product noise one", score=0.0199, source_file="qpack_01_product_manual.txt", chunk_type="fact_line", fact_ids=["F_PRODUCT_001"], markers=["QPACK_PRODUCT_SERUM_001"]),
        _result("product noise two", score=0.0198, source_file="qpack_01_product_manual.txt", chunk_type="fact_line", fact_ids=["F_PRODUCT_005"], markers=["QPACK_PRODUCT_SERUM_005"]),
        _result("report noise", score=0.0197, source_file="qpack_08_ops_weekly_report.txt", chunk_type="fact_line", fact_ids=["F_REPORT_007"], markers=["QPACK_REPORT_007"]),
        _result("promo noise", score=0.0196, source_file="qpack_04_promo_818.txt", chunk_type="fact_line", fact_ids=["F_PROMO_006"], markers=["QPACK_PROMO_818_006"]),
        _result("fact_id=F_SERVICE_002 | marker=QPACK_SERVICE_002 | 过敏反馈SOP", score=0.0180, source_file="qpack_05_after_sales_sop.txt", chunk_type="fact_line", fact_ids=["F_SERVICE_002"], markers=["QPACK_SERVICE_002"]),
        _result("fact_id=F_CONTENT_004 | marker=QPACK_CONTENT_004 | 敏感肌脚本", score=0.0178, source_file="qpack_07_content_script_rules.txt", chunk_type="fact_line", fact_ids=["F_CONTENT_004"], markers=["QPACK_CONTENT_004"]),
    ]

    reranked = HybridRetriever._apply_metadata_boost(query, candidates, top_k=5)
    source_files = {result.source_file for result in reranked}

    assert "qpack_05_after_sales_sop.txt" in source_files
    assert "qpack_07_content_script_rules.txt" in source_files


def test_missing_metadata_keeps_original_order_and_does_not_raise():
    candidates = [
        SearchResult(content="first", rrf_score=0.30),
        SearchResult(content="second", rrf_score=0.20, metadata=None),
        SearchResult(content="third", rrf_score=0.10, metadata="bad-metadata"),
    ]

    reranked = HybridRetriever._apply_metadata_boost("客服 售后", candidates, top_k=3)

    assert [result.content for result in reranked] == ["first", "second", "third"]


def test_fact_line_and_update_notice_receive_small_structural_boosts():
    query = "更新公告优先，价格怎么调整？"
    fact_line = _result(
        "fact_id=F_PROMO_002 | marker=QPACK_PROMO_818_002 | 旧价格",
        score=0.01,
        source_file="qpack_04_promo_818.txt",
        chunk_type="fact_line",
        fact_ids=["F_PROMO_002"],
        markers=["QPACK_PROMO_818_002"],
    )
    update_notice = _result(
        "fact_id=F_UPDATE_001 | marker=QPACK_UPDATE_001 | 新价格公告",
        score=0.01,
        source_file="qpack_09_conflict_update_notice.txt",
        chunk_type="update_notice",
        fact_ids=["F_UPDATE_001"],
        markers=["QPACK_UPDATE_001"],
    )
    paragraph = _result("plain paragraph", score=0.01, chunk_type="paragraph")

    assert _metadata_boost_score(query, update_notice) > _metadata_boost_score(query, fact_line)
    assert _metadata_boost_score(query, fact_line) > _metadata_boost_score(query, paragraph)


def test_service_and_content_risk_terms_map_to_expected_domains():
    service = _result(
        "fact_id=F_SERVICE_002 | marker=QPACK_SERVICE_002 | 过敏反馈提供批号和照片",
        score=0.01,
        source_file="qpack_05_after_sales_sop.txt",
        chunk_type="fact_line",
        fact_ids=["F_SERVICE_002"],
        markers=["QPACK_SERVICE_002"],
    )
    content = _result(
        "fact_id=F_CONTENT_007 | marker=QPACK_CONTENT_007 | 先局部试用并查看成分表",
        score=0.01,
        source_file="qpack_07_content_script_rules.txt",
        chunk_type="fact_line",
        fact_ids=["F_CONTENT_007"],
        markers=["QPACK_CONTENT_007"],
    )
    inventory = _result("inventory fallback", score=0.01, chunk_type="fact_line")

    assert _metadata_boost_score(
        "过敏反馈需要批号照片并暂停使用吗？", service
    ) > _metadata_boost_score("过敏反馈需要批号照片并暂停使用吗？", inventory)
    assert _metadata_boost_score(
        "评论回复是否要先局部试用并查看成分表？", content
    ) > _metadata_boost_score("评论回复是否要先局部试用并查看成分表？", inventory)


def test_rule_fact_with_medical_text_is_not_content_domain_coverage():
    rule = _result(
        "fact_id=F_RULE_002 | marker=QPACK_RULE_002 | 平台规则提到不得给医疗建议",
        score=0.01,
        source_file="qpack_06_platform_rules.txt",
        chunk_type="fact_line",
        fact_ids=["F_RULE_002"],
        markers=["QPACK_RULE_002"],
        section_title="平台合规规则",
    )

    assert _is_fact_line_for_domain(rule, "rule")
    assert not _is_fact_line_for_domain(rule, "content")


def test_fallback_chunk_is_not_unconditionally_penalized():
    fallback = _result(
        "fact_id=F_SERVICE_008 | marker=QPACK_SERVICE_008 | 禁用客服话术",
        score=0.01,
        source_file="qpack_05_after_sales_sop.txt",
        chunk_type="fallback",
        fact_ids=["F_SERVICE_008"],
        markers=["QPACK_SERVICE_008"],
    )

    assert _metadata_boost_score("客服售后话术", fallback) > 0


def test_medical_risk_guard_preserves_service_and_generic_content_fact_lines():
    query = "资料里是否允许客服诊断用户皮肤疾病？"
    candidates = [
        _result("inventory replacement", score=0.0168, source_file="qpack_02_inventory_fulfillment.txt", chunk_type="fact_line", fact_ids=["F_INV_006"], markers=["QPACK_INV_EAST_006"]),
        _result("platform allowed expression", score=0.0167, source_file="qpack_06_platform_rules.txt", chunk_type="fact_line", fact_ids=["F_RULE_002"], markers=["QPACK_RULE_002"]),
        _result("fact_id=F_SERVICE_002 | marker=QPACK_SERVICE_002 | 过敏反馈不得诊断疾病", score=0.0150, source_file="qpack_05_after_sales_sop.txt", chunk_type="fact_line", fact_ids=["F_SERVICE_002"], markers=["QPACK_SERVICE_002"]),
        _result("fact_id=F_CONTENT_OTHER | marker=QPACK_CONTENT_OTHER | 评论区回复先局部试用并查看成分表，不给医疗建议", score=0.0140, source_file="qpack_07_content_script_rules.txt", chunk_type="fact_line", fact_ids=["F_CONTENT_OTHER"], markers=["QPACK_CONTENT_OTHER"]),
    ]

    reranked = HybridRetriever._apply_metadata_boost(query, candidates, top_k=3)
    joined = "\n".join(result.content for result in reranked)

    assert "F_SERVICE_002" in joined
    assert "F_CONTENT_OTHER" in joined


def test_medical_risk_guard_does_not_let_content_displace_service():
    query = "客服诊断皮肤疾病是否允许？"
    candidates = [
        _result("fact_id=F_CONTENT_OTHER | marker=QPACK_CONTENT_OTHER | 评论区回复先局部试用并查看成分表", score=0.0168, source_file="qpack_07_content_script_rules.txt", chunk_type="fact_line", fact_ids=["F_CONTENT_OTHER"], markers=["QPACK_CONTENT_OTHER"]),
        _result("high scoring rule noise", score=0.0167, source_file="qpack_06_platform_rules.txt", chunk_type="fact_line", fact_ids=["F_RULE_002"], markers=["QPACK_RULE_002"]),
        _result("fact_id=F_SERVICE_002 | marker=QPACK_SERVICE_002 | 过敏反馈不得诊断疾病", score=0.0140, source_file="qpack_05_after_sales_sop.txt", chunk_type="fact_line", fact_ids=["F_SERVICE_002"], markers=["QPACK_SERVICE_002"]),
    ]

    reranked = HybridRetriever._apply_metadata_boost(query, candidates, top_k=2)
    joined = "\n".join(result.content for result in reranked)

    assert "F_CONTENT_OTHER" in joined
    assert "F_SERVICE_002" in joined


def test_inventory_query_does_not_trigger_medical_source_guard():
    query = "30ml低于多少瓶触发补货预警？"
    candidates = [
        _result("fact_id=F_PRODUCT_006 | marker=QPACK_PRODUCT_SERUM_006 | 组合装A", score=0.0200, source_file="qpack_01_product_manual.txt", chunk_type="fact_line", fact_ids=["F_PRODUCT_006"], markers=["QPACK_PRODUCT_SERUM_006"]),
        _result("fact_id=F_PRODUCT_001 | marker=QPACK_PRODUCT_SERUM_001 | 30ml建议零售价", score=0.0199, source_file="qpack_01_product_manual.txt", chunk_type="fact_line", fact_ids=["F_PRODUCT_001"], markers=["QPACK_PRODUCT_SERUM_001"]),
        _result("fact_id=F_PRODUCT_002 | marker=QPACK_PRODUCT_SERUM_002 | 15ml建议零售价", score=0.0198, source_file="qpack_01_product_manual.txt", chunk_type="fact_line", fact_ids=["F_PRODUCT_002"], markers=["QPACK_PRODUCT_SERUM_002"]),
        _result("fact_id=F_INV_001 | marker=QPACK_INV_EAST_001 | 30ml华东仓可售库存", score=0.0197, source_file="qpack_02_inventory_fulfillment.txt", chunk_type="fact_line", fact_ids=["F_INV_001"], markers=["QPACK_INV_EAST_001"]),
        _result("fact_id=F_INV_003 | marker=QPACK_INV_EAST_003 | 安全库存30ml低于180瓶触发补货预警", score=0.0196, source_file="qpack_02_inventory_fulfillment.txt", chunk_type="fact_line", fact_ids=["F_INV_003"], markers=["QPACK_INV_EAST_003"]),
        _result("fact_id=F_CONTENT_OTHER | marker=QPACK_CONTENT_OTHER | 评论区医疗建议", score=0.0100, source_file="qpack_07_content_script_rules.txt", chunk_type="fact_line", fact_ids=["F_CONTENT_OTHER"], markers=["QPACK_CONTENT_OTHER"]),
    ]

    reranked = HybridRetriever._apply_metadata_boost(query, candidates, top_k=5)
    joined = "\n".join(result.content for result in reranked)

    assert "F_INV_003" in joined
    assert "F_CONTENT_OTHER" not in joined


def test_medical_candidate_supplement_adds_content_fact_from_indexed_docs():
    retriever = HybridRetriever(company_id="test-company")
    retriever._documents = {
        "content-medical": {
            "content": "fact_id=F_CONTENT_007 | marker=QPACK_CONTENT_007 | 评论区不得给医疗建议，过敏用户先查看成分表并局部试用。",
            "metadata": {
                "source_file": "qpack_07_content_script_rules.txt",
                "chunk_type": "fact_line",
                "fact_ids": ["F_CONTENT_007"],
                "markers": ["QPACK_CONTENT_007"],
                "section_title": "评论区合规",
                "chunk_index": 7,
            },
        }
    }
    query = "资料里是否允许客服诊断用户皮肤疾病？"
    candidates = [
        _result("inventory replacement", score=0.0168, source_file="qpack_02_inventory_fulfillment.txt", chunk_type="fact_line", fact_ids=["F_INV_006"], markers=["QPACK_INV_EAST_006"]),
        _result("platform allowed expression", score=0.0167, source_file="qpack_06_platform_rules.txt", chunk_type="fact_line", fact_ids=["F_RULE_002"], markers=["QPACK_RULE_002"]),
        _result("fact_id=F_SERVICE_002 | marker=QPACK_SERVICE_002 | 过敏反馈不得诊断疾病", score=0.0150, source_file="qpack_05_after_sales_sop.txt", chunk_type="fact_line", fact_ids=["F_SERVICE_002"], markers=["QPACK_SERVICE_002"]),
    ]

    supplemented = retriever._supplement_medical_source_candidates(
        query, candidates, top_k=3
    )
    joined = "\n".join(result.content for result in supplemented)

    assert "F_SERVICE_002" in joined
    assert "F_CONTENT_007" in joined
    assert any(result.source == "metadata_supplement" for result in supplemented)


def test_medical_candidate_supplement_uses_structured_content_metadata_fallback():
    retriever = HybridRetriever(company_id="test-company")
    retriever._documents = {
        "content-metadata-fallback": {
            "content": "garbled payload without readable medical source hints",
            "metadata": {
                "source_file": "qpack_07_content_script_rules.txt",
                "chunk_type": "fact_line",
                "fact_ids": ["F_CONTENT_META"],
                "markers": ["QPACK_CONTENT_META"],
                "section_title": "评论区合规",
                "chunk_index": 9,
            },
        }
    }
    query = "资料里是否允许客服诊断用户皮肤疾病？"
    candidates = [
        _result("fact_id=F_RULE_002 | marker=QPACK_RULE_002 | 平台规则提到不得给医疗建议", score=0.0167, source_file="qpack_06_platform_rules.txt", chunk_type="fact_line", fact_ids=["F_RULE_002"], markers=["QPACK_RULE_002"]),
        _result("fact_id=F_SERVICE_002 | marker=QPACK_SERVICE_002 | 过敏反馈不得诊断疾病", score=0.0150, source_file="qpack_05_after_sales_sop.txt", chunk_type="fact_line", fact_ids=["F_SERVICE_002"], markers=["QPACK_SERVICE_002"]),
    ]

    supplemented = retriever._supplement_medical_source_candidates(
        query, candidates, top_k=3
    )
    joined = "\n".join(result.content for result in supplemented)
    fact_ids = {
        fact_id
        for result in supplemented
        for fact_id in (result.metadata or {}).get("fact_ids", [])
    }

    assert "F_SERVICE_002" in joined
    assert "F_CONTENT_META" in fact_ids
    assert any(result.source == "metadata_supplement" for result in supplemented)
    assert not any(
        _is_fact_line_for_domain(result, "content")
        for result in candidates
        if "F_RULE_002" in (result.metadata or {}).get("fact_ids", [])
    )


def test_medical_candidate_supplement_falls_back_to_vector_documents():
    retriever = HybridRetriever(company_id="test-company")
    retriever._documents = {}
    retriever.vector = _VectorDocs(
        [
            {
                "id": "vector-content-meta",
                "content": "fact_id=F_CONTENT_META | marker=QPACK_CONTENT_META | 评论区不得给医疗建议，先查看成分表并局部试用。",
                "metadata": {
                    "source_file": "qpack_07_content_script_rules.txt",
                    "chunk_type": "fact_line",
                    "fact_ids": ["F_CONTENT_META"],
                    "markers": ["QPACK_CONTENT_META"],
                    "section_title": "评论区合规",
                    "chunk_index": 9,
                },
            }
        ]
    )
    query = "资料里是否允许客服诊断用户皮肤疾病？"
    candidates = [
        _result("fact_id=F_RULE_002 | marker=QPACK_RULE_002 | 平台规则提到不得给医疗建议", score=0.0167, source_file="qpack_06_platform_rules.txt", chunk_type="fact_line", fact_ids=["F_RULE_002"], markers=["QPACK_RULE_002"]),
        _result("fact_id=F_SERVICE_002 | marker=QPACK_SERVICE_002 | 过敏反馈不得诊断疾病", score=0.0150, source_file="qpack_05_after_sales_sop.txt", chunk_type="fact_line", fact_ids=["F_SERVICE_002"], markers=["QPACK_SERVICE_002"]),
    ]

    supplemented = retriever._supplement_medical_source_candidates(
        query, candidates, top_k=3
    )
    fact_ids = {
        fact_id
        for result in supplemented
        for fact_id in (result.metadata or {}).get("fact_ids", [])
    }

    assert retriever.vector.calls == 1
    assert "F_CONTENT_META" in fact_ids
    assert any(result.source == "metadata_supplement" for result in supplemented)
    counters = retriever._last_medical_supplement_debug
    assert counters is not None
    assert counters["vector_list_documents_called"] is True
    assert counters["vector_listed_doc_count"] == 1
    assert counters["vector_content_fact_count"] == 1
    assert counters["supplement_added_content_count"] == 1


def test_medical_candidate_supplement_does_not_skip_for_generic_content_gap():
    retriever = HybridRetriever(company_id="test-company")
    retriever._documents = {}
    retriever.vector = _VectorDocs(
        [
            {
                "id": "vector-content-meta",
                "content": "fact_id=F_CONTENT_META | marker=QPACK_CONTENT_META | 评论区不得给医疗建议，过敏用户先查看成分表并局部试用。",
                "metadata": {
                    "source_file": "qpack_07_content_script_rules.txt",
                    "chunk_type": "fact_line",
                    "fact_ids": ["F_CONTENT_META"],
                    "markers": ["QPACK_CONTENT_META"],
                    "section_title": "评论区合规",
                    "chunk_index": 9,
                },
            }
        ]
    )
    generic_content = _result(
        "fact_id=F_CONTENT_GENERIC | marker=QPACK_CONTENT_GENERIC | 普通内容素材",
        score=0.0160,
        source_file="qpack_07_content_script_rules.txt",
        chunk_type="fact_line",
        fact_ids=["F_CONTENT_GENERIC"],
        markers=["QPACK_CONTENT_GENERIC"],
        section_title="普通内容",
    )
    service = _result(
        "fact_id=F_SERVICE_META | marker=QPACK_SERVICE_META | 过敏反馈不得诊断疾病",
        score=0.0150,
        source_file="qpack_05_after_sales_sop.txt",
        chunk_type="fact_line",
        fact_ids=["F_SERVICE_META"],
        markers=["QPACK_SERVICE_META"],
    )

    supplemented = retriever._supplement_medical_source_candidates(
        "资料里是否允许客服诊断用户皮肤疾病？",
        [generic_content, service],
        top_k=3,
    )
    fact_ids = {
        fact_id
        for result in supplemented
        for fact_id in (result.metadata or {}).get("fact_ids", [])
    }
    counters = retriever._last_medical_supplement_debug

    assert _is_fact_line_for_domain(generic_content, "content")
    assert not _is_medical_evidence_content_fact_line(generic_content)
    assert retriever.vector.calls == 1
    assert "F_CONTENT_META" in fact_ids
    assert counters is not None
    assert counters["content_domain_present"] is True
    assert counters["medical_evidence_content_present"] is False
    assert counters["supplement_skip_reason_code"] == "emitted"
    assert counters["vector_medical_evidence_content_count"] == 1
    assert counters["supplement_added_medical_evidence_content_count"] == 1


def test_medical_candidate_supplement_debug_counters_are_non_sensitive():
    retriever = HybridRetriever(company_id="test-company")
    retriever._documents = {}
    retriever.vector = _VectorDocs(
        [
            {
                "id": "vector-content-meta",
                "content": "UNSAFE_DOC_CONTENT should never appear in counters",
                "metadata": {
                    "source_file": "qpack_07_content_script_rules.txt",
                    "chunk_type": "fact_line",
                    "fact_ids": ["F_CONTENT_META"],
                    "markers": ["QPACK_CONTENT_META"],
                    "section_title": "评论区合规",
                    "chunk_index": 9,
                },
            }
        ]
    )
    candidates = [
        _result("fact_id=F_SERVICE_002 | marker=QPACK_SERVICE_002 | 过敏反馈不得诊断疾病", score=0.0150, source_file="qpack_05_after_sales_sop.txt", chunk_type="fact_line", fact_ids=["F_SERVICE_002"], markers=["QPACK_SERVICE_002"]),
    ]

    retriever._supplement_medical_source_candidates(
        "客服诊断皮肤疾病是否允许？", candidates, top_k=3
    )
    counters = retriever._last_medical_supplement_debug

    assert counters is not None
    assert counters["medical_supplement_enabled"] is True
    assert all(isinstance(value, (bool, int, str)) for value in counters.values())
    serialized = str(counters)
    assert "UNSAFE_DOC_CONTENT" not in serialized
    assert "客服诊断皮肤疾病是否允许" not in serialized
    assert "qpack_07_content_script_rules" not in serialized
    assert "F_CONTENT_META" not in serialized
    assert "QPACK_CONTENT_META" not in serialized


def test_medical_candidate_supplement_logs_final_debug_counters(monkeypatch):
    events = []

    def capture(event_name, **kwargs):
        events.append((event_name, kwargs))

    monkeypatch.setattr(hybrid_module.logger, "info", capture)
    retriever = HybridRetriever(company_id="test-company")
    final = [
        _result("fact_id=F_SERVICE_002 | marker=QPACK_SERVICE_002 | 过敏反馈不得诊断疾病", score=0.0150, source_file="qpack_05_after_sales_sop.txt", chunk_type="fact_line", fact_ids=["F_SERVICE_002"], markers=["QPACK_SERVICE_002"]),
        _result("fact_id=F_CONTENT_META | marker=QPACK_CONTENT_META | 评论区不得给医疗建议", score=0.0140, source_file="qpack_07_content_script_rules.txt", chunk_type="fact_line", fact_ids=["F_CONTENT_META"], markers=["QPACK_CONTENT_META"]),
    ]
    retriever._last_medical_supplement_debug = {
        "medical_supplement_enabled": True,
        "local_doc_count": 0,
        "vector_list_documents_called": True,
        "vector_list_documents_error": False,
        "vector_list_documents_missing": False,
        "vector_listed_doc_count": 1,
        "local_content_fact_count": 0,
        "local_medical_evidence_content_fact_count": 0,
        "local_service_fact_count": 0,
        "vector_content_fact_count": 1,
        "vector_medical_evidence_content_count": 1,
        "vector_service_fact_count": 0,
        "content_domain_present": True,
        "medical_evidence_content_present": True,
        "supplement_seen_content_domain": True,
        "supplement_seen_service_domain": True,
        "supplement_added_count": 1,
        "supplement_added_content_count": 1,
        "supplement_added_medical_evidence_content_count": 1,
        "supplement_added_service_count": 0,
        "post_supplement_candidate_count": 3,
        "reranker_candidate_content_domain_present": True,
        "reranker_candidate_medical_evidence_content_present": True,
        "reranker_candidate_service_domain_present": True,
        "guard_candidate_content_domain_present": True,
        "guard_candidate_medical_evidence_content_present": True,
        "guard_candidate_service_domain_present": True,
        "final_content_domain_present": False,
        "final_medical_evidence_content_present": False,
        "final_service_domain_present": False,
    }

    retriever._finalize_medical_supplement_debug(final)

    assert events == [
        (
            "medical_supplement_debug_counters",
            retriever._last_medical_supplement_debug,
        )
    ]
    counters = events[0][1]
    assert counters["final_content_domain_present"] is True
    assert counters["final_medical_evidence_content_present"] is True
    assert counters["final_service_domain_present"] is True
    assert counters["reranker_candidate_content_domain_present"] is True
    assert counters["reranker_candidate_medical_evidence_content_present"] is True
    assert counters["guard_candidate_content_domain_present"] is True
    assert counters["guard_candidate_medical_evidence_content_present"] is True
    assert isinstance(counters["final_content_domain_present"], bool)
    assert isinstance(counters["final_medical_evidence_content_present"], bool)
    assert "final_has_content" not in counters
    assert "reranker_candidate_has_content" not in counters
    assert "guard_candidate_has_content" not in counters


def test_medical_search_path_logs_debug_counters_when_no_supplement_added(monkeypatch):
    events = []

    def capture(event_name, **kwargs):
        events.append((event_name, kwargs))

    monkeypatch.setattr(hybrid_module.logger, "info", capture)
    retriever = HybridRetriever(company_id="test-company")
    retriever._embedding_service = _EmbeddingService()
    retriever.vector = _VectorDocs([])
    retriever._documents = {
        "service-medical": {
            "content": "fact_id=F_SERVICE_002 | marker=QPACK_SERVICE_002 | 客服诊断皮肤疾病时过敏反馈不得诊断疾病",
            "metadata": {
                "source_file": "qpack_05_after_sales_sop.txt",
                "chunk_type": "fact_line",
                "fact_ids": ["F_SERVICE_002"],
                "markers": ["QPACK_SERVICE_002"],
            },
        }
    }
    retriever._rebuild_bm25()

    results = retriever.search("客服诊断皮肤疾病是否允许？", top_k=1, use_reranker=False)

    assert results
    event = next(
        item for item in events if item[0] == "medical_supplement_debug_counters"
    )
    counters = event[1]
    assert counters["medical_query_detected"] is True
    assert counters["supplement_function_invoked"] is True
    assert counters["supplement_skipped"] is True
    assert counters["supplement_skip_reason_code"] == "no_candidates"
    assert counters["logger_emitted"] is True
    assert counters["final_content_domain_present"] is False
    assert counters["final_medical_evidence_content_present"] is False
    assert counters["final_service_domain_present"] is True
    assert isinstance(counters["final_content_domain_present"], bool)
    assert isinstance(counters["final_medical_evidence_content_present"], bool)
    assert "final_has_content" not in counters
    assert "reranker_candidate_has_content" not in counters
    assert "guard_candidate_has_content" not in counters
    assert all(isinstance(value, (bool, int, str)) for value in counters.values())
    serialized = str(counters)
    assert "客服诊断皮肤疾病是否允许" not in serialized
    assert "qpack_05_after_sales_sop" not in serialized
    assert "F_SERVICE_002" not in serialized
    assert "QPACK_SERVICE_002" not in serialized


def test_inventory_search_path_does_not_log_medical_debug_counters(monkeypatch):
    events = []

    def capture(event_name, **kwargs):
        events.append((event_name, kwargs))

    monkeypatch.setattr(hybrid_module.logger, "info", capture)
    retriever = HybridRetriever(company_id="test-company")
    retriever._embedding_service = _EmbeddingService()
    retriever.vector = _VectorDocs([])
    retriever._documents = {
        "inventory": {
            "content": "fact_id=F_INV_003 | marker=QPACK_INV_EAST_003 | 30ml低于180瓶触发补货预警",
            "metadata": {
                "source_file": "qpack_02_inventory_fulfillment.txt",
                "chunk_type": "fact_line",
                "fact_ids": ["F_INV_003"],
                "markers": ["QPACK_INV_EAST_003"],
            },
        }
    }
    retriever._rebuild_bm25()

    retriever.search("30ml低于多少瓶触发补货预警？", top_k=1, use_reranker=False)

    assert not any(
        event_name == "medical_supplement_debug_counters"
        for event_name, _ in events
    )


def test_medical_candidate_supplement_vector_fallback_deduplicates_chunks():
    retriever = HybridRetriever(company_id="test-company")
    row = {
        "id": "vector-content-meta",
        "content": "fact_id=F_CONTENT_META | marker=QPACK_CONTENT_META | 评论区不得给医疗建议，先查看成分表并局部试用。",
        "metadata": {
            "source_file": "qpack_07_content_script_rules.txt",
            "chunk_type": "fact_line",
            "fact_ids": ["F_CONTENT_META"],
            "markers": ["QPACK_CONTENT_META"],
            "chunk_index": 9,
        },
    }
    retriever.vector = _VectorDocs([row, dict(row)])
    candidates = [
        _result("fact_id=F_SERVICE_002 | marker=QPACK_SERVICE_002 | 过敏反馈不得诊断疾病", score=0.0150, source_file="qpack_05_after_sales_sop.txt", chunk_type="fact_line", fact_ids=["F_SERVICE_002"], markers=["QPACK_SERVICE_002"]),
    ]

    supplemented = retriever._supplement_medical_source_candidates(
        "客服诊断皮肤疾病是否允许？", candidates, top_k=3
    )
    content_supplements = [
        result
        for result in supplemented
        if "F_CONTENT_META" in (result.metadata or {}).get("fact_ids", [])
    ]

    assert len(content_supplements) == 1


def test_medical_candidate_supplement_vector_fallback_not_used_for_inventory_query():
    retriever = HybridRetriever(company_id="test-company")
    retriever.vector = _VectorDocs(
        [
            {
                "id": "vector-content-meta",
                "content": "fact_id=F_CONTENT_META | marker=QPACK_CONTENT_META | 评论区不得给医疗建议。",
                "metadata": {
                    "source_file": "qpack_07_content_script_rules.txt",
                    "chunk_type": "fact_line",
                    "fact_ids": ["F_CONTENT_META"],
                    "markers": ["QPACK_CONTENT_META"],
                },
            }
        ]
    )
    candidates = [
        _result("fact_id=F_INV_003 | marker=QPACK_INV_EAST_003 | 安全库存30ml低于180瓶触发补货预警", score=0.0196, source_file="qpack_02_inventory_fulfillment.txt", chunk_type="fact_line", fact_ids=["F_INV_003"], markers=["QPACK_INV_EAST_003"]),
    ]

    supplemented = retriever._supplement_medical_source_candidates(
        "30ml低于多少瓶触发补货预警？", candidates, top_k=2
    )

    assert retriever.vector.calls == 0
    assert supplemented == candidates
    assert retriever._last_medical_supplement_debug is None


def test_medical_candidate_supplement_vector_fallback_handles_list_failure():
    retriever = HybridRetriever(company_id="test-company")
    retriever._documents = {}
    retriever.vector = _VectorDocs(exc=RuntimeError("list failed"))
    service = _result(
        "fact_id=F_SERVICE_002 | marker=QPACK_SERVICE_002 | 过敏反馈不得诊断疾病",
        score=0.0150,
        source_file="qpack_05_after_sales_sop.txt",
        chunk_type="fact_line",
        fact_ids=["F_SERVICE_002"],
        markers=["QPACK_SERVICE_002"],
    )

    supplemented = retriever._supplement_medical_source_candidates(
        "客服诊断皮肤疾病是否允许？", [service], top_k=2
    )

    assert retriever.vector.calls == 1
    assert supplemented == [service]
    counters = retriever._last_medical_supplement_debug
    assert counters is not None
    assert counters["vector_list_documents_called"] is True
    assert counters["vector_list_documents_error"] is True
    assert counters["post_supplement_candidate_count"] == 1


def test_medical_candidate_supplement_vector_fallback_handles_missing_list_documents():
    retriever = HybridRetriever(company_id="test-company")
    retriever._documents = {}
    retriever.vector = object()
    service = _result(
        "fact_id=F_SERVICE_002 | marker=QPACK_SERVICE_002 | 过敏反馈不得诊断疾病",
        score=0.0150,
        source_file="qpack_05_after_sales_sop.txt",
        chunk_type="fact_line",
        fact_ids=["F_SERVICE_002"],
        markers=["QPACK_SERVICE_002"],
    )

    supplemented = retriever._supplement_medical_source_candidates(
        "客服诊断皮肤疾病是否允许？", [service], top_k=2
    )

    assert supplemented == [service]


def test_medical_candidate_supplement_does_not_run_for_inventory_query():
    retriever = HybridRetriever(company_id="test-company")
    retriever._documents = {
        "content-medical": {
            "content": "fact_id=F_CONTENT_007 | marker=QPACK_CONTENT_007 | 评论区不得给医疗建议，过敏用户先查看成分表并局部试用。",
            "metadata": {
                "source_file": "qpack_07_content_script_rules.txt",
                "chunk_type": "fact_line",
                "fact_ids": ["F_CONTENT_007"],
                "markers": ["QPACK_CONTENT_007"],
            },
        }
    }
    candidates = [
        _result("fact_id=F_INV_003 | marker=QPACK_INV_EAST_003 | 安全库存30ml低于180瓶触发补货预警", score=0.0196, source_file="qpack_02_inventory_fulfillment.txt", chunk_type="fact_line", fact_ids=["F_INV_003"], markers=["QPACK_INV_EAST_003"]),
        _result("fact_id=F_PRODUCT_001 | marker=QPACK_PRODUCT_SERUM_001 | 30ml建议零售价", score=0.0195, source_file="qpack_01_product_manual.txt", chunk_type="fact_line", fact_ids=["F_PRODUCT_001"], markers=["QPACK_PRODUCT_SERUM_001"]),
    ]

    supplemented = retriever._supplement_medical_source_candidates(
        "30ml低于多少瓶触发补货预警？", candidates, top_k=2
    )

    assert supplemented == candidates


def test_medical_candidate_supplement_preserves_absence_disclaimer():
    retriever = HybridRetriever(company_id="test-company")
    retriever._documents = {
        "content-medical": {
            "content": "fact_id=F_CONTENT_007 | marker=QPACK_CONTENT_007 | 评论区不得给医疗建议，过敏用户先查看成分表并局部试用。",
            "metadata": {
                "source_file": "qpack_07_content_script_rules.txt",
                "chunk_type": "fact_line",
                "fact_ids": ["F_CONTENT_007"],
                "markers": ["QPACK_CONTENT_007"],
            },
        }
    }
    disclaimer = _result(
        "本文件为 public-demo synthetic 测试资料，不对应任何真实商家或个人。",
        score=0.015,
        source_file="qpack_03_kol_matrix.txt",
        chunk_type="paragraph",
    )

    supplemented = retriever._supplement_medical_source_candidates(
        "资料里是否给出了真实达人账号链接？", [disclaimer], top_k=1
    )

    assert supplemented == [disclaimer]


def test_medical_candidate_supplement_handles_missing_metadata():
    retriever = HybridRetriever(company_id="test-company")
    retriever._documents = {
        "bad-metadata": {
            "content": "评论区不得给医疗建议，过敏用户先查看成分表并局部试用。",
            "metadata": None,
        }
    }
    service = _result(
        "fact_id=F_SERVICE_002 | marker=QPACK_SERVICE_002 | 过敏反馈不得诊断疾病",
        score=0.0150,
        source_file="qpack_05_after_sales_sop.txt",
        chunk_type="fact_line",
        fact_ids=["F_SERVICE_002"],
        markers=["QPACK_SERVICE_002"],
    )

    supplemented = retriever._supplement_medical_source_candidates(
        "客服诊断皮肤疾病是否允许？", [service], top_k=1
    )

    assert supplemented == [service]
