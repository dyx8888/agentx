import os
import sys

sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.rag.hybrid_retriever import (
    HybridRetriever,
    SearchResult,
    _metadata_boost_score,
)


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
                "section_title": "script compliance",
                "chunk_index": 9,
            },
        }
    }
    query = "资料里是否允许客服诊断用户皮肤疾病？"
    candidates = [
        _result("platform allowed expression", score=0.0167, source_file="qpack_06_platform_rules.txt", chunk_type="fact_line", fact_ids=["F_RULE_002"], markers=["QPACK_RULE_002"]),
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
