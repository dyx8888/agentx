import json
import tempfile
from pathlib import Path
from typing import Any


MAX_CONTENT_EXCERPT_CHARS = 160
TOP_K_DIAGNOSTIC_LIMIT = 5
ABSENCE_EVIDENCE_TERMS = (
    "synthetic",
    "测试资料",
    "不对应任何真实商家或个人",
    "不对应真实商家",
    "虚构",
    "不包含真实",
    "不含真实",
    "没有真实",
    "无真实",
)
PURE_ABSENCE_HINTS = (
    "真实",
    "real",
    "link",
    "链接",
    "账号",
    "手机号",
    "订单号",
    "客户信息",
    "真实客户",
    "真实达人",
    "真实商家",
)
CONCRETE_NEGATIVE_FACT_HINTS = (
    "允许",
    "承诺",
    "诊断",
    "疾病",
    "无限量",
    "销售",
    "祛痘",
    "医学",
    "功效",
    "客服",
)


def default_search_diagnostics_path() -> Path:
    return (
        Path(tempfile.gettempdir())
        / "agentx-2c-rag-quality-pack"
        / "search_top5_diagnostics.jsonl"
    )


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in _as_list(value) if item not in (None, "")]


def _metadata(result: dict[str, Any]) -> dict[str, Any]:
    metadata = result.get("metadata") or {}
    return metadata if isinstance(metadata, dict) else {}


def _terms_in_result(result: dict[str, Any], field: str) -> set[str]:
    metadata = _metadata(result)
    terms = set(_string_list(metadata.get(field)))
    terms.update(_string_list(result.get(field)))
    content = str(result.get("content") or "")
    terms.update(term for term in terms if term and term in content)
    return terms


def _contains_term(result: dict[str, Any], term: str, field: str) -> bool:
    if term in _terms_in_result(result, field):
        return True
    return term in str(result.get("content") or "")


def _excerpt(content: Any, limit: int = MAX_CONTENT_EXCERPT_CHARS) -> str:
    compact = " ".join(str(content or "").split())
    return compact[:limit]


def _source_file(result: dict[str, Any]) -> str:
    metadata = _metadata(result)
    return str(
        result.get("source_file")
        or metadata.get("source_file")
        or metadata.get("original_filename")
        or ""
    )


def _chunk_index(result: dict[str, Any]) -> int | None:
    metadata = _metadata(result)
    value = result.get("chunk_index", metadata.get("chunk_index"))
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ranked_top5(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    top5: list[dict[str, Any]] = []
    for rank, result in enumerate(results[:TOP_K_DIAGNOSTIC_LIMIT], start=1):
        metadata = _metadata(result)
        top5.append(
            {
                "rank": rank,
                "score": result.get("score"),
                "source_file": _source_file(result),
                "chunk_index": _chunk_index(result),
                "chunk_type": metadata.get("chunk_type"),
                "section_title": metadata.get("section_title"),
                "fact_ids": _string_list(metadata.get("fact_ids") or result.get("fact_ids")),
                "markers": _string_list(metadata.get("markers") or result.get("markers")),
                "content_excerpt": _excerpt(result.get("content")),
            }
        )
    return top5


def _combined_scoring_text(
    question: dict[str, Any],
    ground_truth: dict[str, Any],
) -> str:
    return " ".join(
        str(value or "")
        for value in (
            question.get("question"),
            question.get("category"),
            ground_truth.get("category"),
            ground_truth.get("expected_answer"),
        )
    )


def _contains_casefolded(text: str, term: str) -> bool:
    return term.casefold() in text.casefold()


def _absence_evidence_terms(search_results: list[dict[str, Any]]) -> list[str]:
    top5_text = "\n".join(
        str(result.get("content") or "") for result in search_results[:TOP_K_DIAGNOSTIC_LIMIT]
    )
    return [
        term
        for term in ABSENCE_EVIDENCE_TERMS
        if _contains_casefolded(top5_text, term)
    ]


def _is_pure_absence_question(
    category: str,
    scoring_text: str,
    has_required_evidence: bool,
) -> bool:
    if category != "negative_absent":
        return False
    if not has_required_evidence:
        return True

    has_absence_hint = any(
        _contains_casefolded(scoring_text, term) for term in PURE_ABSENCE_HINTS
    )
    has_concrete_fact_hint = any(term in scoring_text for term in CONCRETE_NEGATIVE_FACT_HINTS)
    return has_absence_hint and not has_concrete_fact_hint


def _metric_bucket(
    category: str,
    has_required_evidence: bool,
    absence_applicable: bool,
) -> str:
    if absence_applicable:
        return "absence_evidence"
    if category == "multi_file_synthesis":
        return "multi_file_coverage"
    if category == "boundary_compliance":
        return "compliance_coverage"
    if has_required_evidence:
        return "fact_recall"
    return "not_applicable"


def _coverage_status(
    *,
    absence_applicable: bool,
    absence_hit_at_5: bool,
    has_required_evidence: bool,
    any_required_hit_at_5: bool | None,
    all_required_hit_at_5: bool | None,
) -> str:
    if absence_applicable:
        return "absent_evidence" if absence_hit_at_5 else "miss"
    if not has_required_evidence:
        return "not_applicable"
    if all_required_hit_at_5:
        return "full"
    if any_required_hit_at_5:
        return "partial"
    return "miss"


def _scoring_notes(
    *,
    metric_bucket: str,
    absence_applicable: bool,
    absence_hit_at_5: bool,
) -> str:
    if absence_applicable and absence_hit_at_5:
        return "absence evidence satisfied by no-real-data or synthetic disclaimer"
    if absence_applicable:
        return "absence evidence question without no-real-data disclaimer in top5"
    if metric_bucket in {"multi_file_coverage", "compliance_coverage"}:
        return "tracked by all-required evidence coverage, not ordinary fact recall"
    if metric_bucket == "fact_recall":
        return "ordinary fact/marker recall"
    return "no required evidence terms"


def build_search_diagnostic_record(
    question: dict[str, Any],
    ground_truth: dict[str, Any],
    search_results: list[dict[str, Any]],
) -> dict[str, Any]:
    category = str(question.get("category") or ground_truth.get("category") or "")
    required_fact_ids = _string_list(ground_truth.get("required_fact_ids"))
    required_markers = _string_list(
        ground_truth.get("required_markers")
        or ground_truth.get("expected_source_markers")
    )
    has_required_evidence = bool(required_fact_ids or required_markers)
    scoring_text = _combined_scoring_text(question, ground_truth)
    absence_applicable = _is_pure_absence_question(
        category,
        scoring_text,
        has_required_evidence,
    )
    matched_absence_terms = _absence_evidence_terms(search_results)
    absence_hit_at_5 = absence_applicable and bool(matched_absence_terms)
    metric_bucket = _metric_bucket(category, has_required_evidence, absence_applicable)
    recall_applicable = metric_bucket == "fact_recall"

    fact_rank: dict[str, int] = {}
    marker_rank: dict[str, int] = {}
    for rank, result in enumerate(search_results[:TOP_K_DIAGNOSTIC_LIMIT], start=1):
        for fact_id in required_fact_ids:
            if fact_id not in fact_rank and _contains_term(result, fact_id, "fact_ids"):
                fact_rank[fact_id] = rank
        for marker in required_markers:
            if marker not in marker_rank and _contains_term(result, marker, "markers"):
                marker_rank[marker] = rank

    matched_ranks = list(fact_rank.values()) + list(marker_rank.values())
    mrr_rank = min(matched_ranks) if matched_ranks else None
    missing_required_fact_ids = [
        fact_id for fact_id in required_fact_ids if fact_id not in fact_rank
    ]
    missing_required_markers = [
        marker for marker in required_markers if marker not in marker_rank
    ]
    any_required_hit_at_5 = None if not has_required_evidence else bool(matched_ranks)
    all_required_hit_at_5 = (
        None
        if not has_required_evidence
        else not missing_required_fact_ids and not missing_required_markers
    )
    partial_required_hit_at_5 = (
        None
        if not has_required_evidence
        else bool(any_required_hit_at_5 and not all_required_hit_at_5)
    )
    coverage_status = _coverage_status(
        absence_applicable=absence_applicable,
        absence_hit_at_5=absence_hit_at_5,
        has_required_evidence=has_required_evidence,
        any_required_hit_at_5=any_required_hit_at_5,
        all_required_hit_at_5=all_required_hit_at_5,
    )

    return {
        "question_id": question.get("question_id") or ground_truth.get("question_id"),
        "category": category,
        "query": question.get("question", ""),
        "required_fact_ids": required_fact_ids,
        "required_markers": required_markers,
        "required_files": _string_list(ground_truth.get("required_files")),
        "metric_bucket": metric_bucket,
        "recall_applicable": recall_applicable,
        "fact_recall_applicable": recall_applicable,
        "hit_at_3": None if not recall_applicable else any(rank <= 3 for rank in matched_ranks),
        "hit_at_5": None if not recall_applicable else bool(matched_ranks),
        "any_required_hit_at_5": any_required_hit_at_5,
        "all_required_hit_at_5": all_required_hit_at_5,
        "partial_required_hit_at_5": partial_required_hit_at_5,
        "absence_applicable": absence_applicable,
        "absence_hit_at_5": absence_hit_at_5,
        "absence_evidence_terms": matched_absence_terms if absence_applicable else [],
        "coverage_status": coverage_status,
        "scoring_notes": _scoring_notes(
            metric_bucket=metric_bucket,
            absence_applicable=absence_applicable,
            absence_hit_at_5=absence_hit_at_5,
        ),
        "missing_required_fact_ids": missing_required_fact_ids,
        "missing_required_markers": missing_required_markers,
        "mrr_rank": mrr_rank if recall_applicable else None,
        "top5": _ranked_top5(search_results),
    }


def write_search_diagnostics_jsonl(
    records: list[dict[str, Any]],
    output_path: Path | None = None,
) -> Path:
    path = output_path or default_search_diagnostics_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def test_required_marker_hit_in_top5_sets_hit_at_5_true():
    record = build_search_diagnostic_record(
        {"question_id": "Q001", "category": "single_file_fact", "question": "price?"},
        {
            "question_id": "Q001",
            "required_fact_ids": ["F_PRODUCT_001"],
            "expected_source_markers": ["QPACK_PRODUCT_SERUM_001"],
            "required_files": ["product.txt"],
        },
        [
            {"content": "noise", "metadata": {"markers": ["OTHER"]}},
            {
                "content": "fact_id=F_PRODUCT_001 marker=QPACK_PRODUCT_SERUM_001",
                "score": 0.9,
                "metadata": {
                    "source_file": "product.txt",
                    "chunk_index": 3,
                    "chunk_type": "fact_line",
                    "section_title": "商品基础",
                    "fact_ids": ["F_PRODUCT_001"],
                    "markers": ["QPACK_PRODUCT_SERUM_001"],
                },
            },
        ],
    )

    assert record["hit_at_3"] is True
    assert record["hit_at_5"] is True
    assert record["metric_bucket"] == "fact_recall"
    assert record["recall_applicable"] is True
    assert record["any_required_hit_at_5"] is True
    assert record["all_required_hit_at_5"] is True
    assert record["partial_required_hit_at_5"] is False
    assert record["coverage_status"] == "full"
    assert record["missing_required_fact_ids"] == []
    assert record["missing_required_markers"] == []
    assert record["mrr_rank"] == 2


def test_required_marker_outside_top5_is_recorded_missing():
    results = [
        {"content": f"noise {idx}", "metadata": {"markers": [f"NOISE_{idx}"]}}
        for idx in range(5)
    ]
    results.append(
        {
            "content": "late marker QPACK_UPDATE_003",
            "metadata": {"markers": ["QPACK_UPDATE_003"], "fact_ids": ["F_UPDATE_003"]},
        }
    )

    record = build_search_diagnostic_record(
        {"question_id": "Q013", "category": "multi_file_synthesis", "question": "stock?"},
        {
            "question_id": "Q013",
            "required_fact_ids": ["F_UPDATE_003"],
            "expected_source_markers": ["QPACK_UPDATE_003"],
        },
        results,
    )

    assert record["metric_bucket"] == "multi_file_coverage"
    assert record["recall_applicable"] is False
    assert record["hit_at_3"] is None
    assert record["hit_at_5"] is None
    assert record["any_required_hit_at_5"] is False
    assert record["all_required_hit_at_5"] is False
    assert record["partial_required_hit_at_5"] is False
    assert record["coverage_status"] == "miss"
    assert record["missing_required_fact_ids"] == ["F_UPDATE_003"]
    assert record["missing_required_markers"] == ["QPACK_UPDATE_003"]
    assert record["mrr_rank"] is None
    assert len(record["top5"]) == 5


def test_no_required_terms_marks_recall_not_applicable():
    record = build_search_diagnostic_record(
        {
            "question_id": "Q024",
            "category": "negative_absent",
            "question": "contains real customer info?",
        },
        {"question_id": "Q024", "required_fact_ids": [], "expected_source_markers": []},
        [{"content": "synthetic-only statement", "metadata": {"chunk_type": "paragraph"}}],
    )

    assert record["recall_applicable"] is False
    assert record["metric_bucket"] == "absence_evidence"
    assert record["hit_at_3"] is None
    assert record["hit_at_5"] is None
    assert record["mrr_rank"] is None
    assert record["absence_applicable"] is True
    assert record["absence_hit_at_5"] is True
    assert record["coverage_status"] == "absent_evidence"
    assert record["missing_required_fact_ids"] == []
    assert record["missing_required_markers"] == []


def test_top5_metadata_and_excerpt_are_preserved_safely():
    long_content = " ".join(["content"] * 80)
    record = build_search_diagnostic_record(
        {"question_id": "Q028", "category": "boundary_compliance", "question": "claim?"},
        {
            "question_id": "Q028",
            "required_fact_ids": ["F_RULE_001"],
            "expected_source_markers": ["QPACK_RULE_001"],
        },
        [
            {
                "content": long_content,
                "score": 0.7,
                "metadata": {
                    "source_file": "rules.txt",
                    "chunk_index": "4",
                    "chunk_type": "fact_line",
                    "section_title": "平台规则",
                    "fact_ids": ["F_RULE_001"],
                    "markers": ["QPACK_RULE_001"],
                },
            }
        ],
    )

    top = record["top5"][0]
    assert record["metric_bucket"] == "compliance_coverage"
    assert record["recall_applicable"] is False
    assert record["any_required_hit_at_5"] is True
    assert record["all_required_hit_at_5"] is True
    assert record["coverage_status"] == "full"
    assert top["chunk_type"] == "fact_line"
    assert top["section_title"] == "平台规则"
    assert top["fact_ids"] == ["F_RULE_001"]
    assert top["markers"] == ["QPACK_RULE_001"]
    assert len(top["content_excerpt"]) == MAX_CONTENT_EXCERPT_CHARS


def test_q025_negative_absent_uses_disclaimer_as_absence_evidence():
    record = build_search_diagnostic_record(
        {
            "question_id": "Q025",
            "category": "negative_absent",
            "question": "资料里是否给出了真实达人账号链接？",
        },
        {
            "question_id": "Q025",
            "category": "negative_absent",
            "expected_answer": "不包含真实达人账号链接，达人均为虚构",
            "required_fact_ids": ["F_KOL_001", "F_KOL_004"],
            "expected_source_markers": ["QPACK_KOL_LINYA_001", "QPACK_KOL_MIMO_001"],
        },
        [
            {
                "content": "本文件为 public-demo synthetic 测试资料，不对应任何真实商家或个人。段落: 达人矩阵",
                "metadata": {"chunk_type": "paragraph", "source_file": "qpack_03_kol_matrix.txt"},
            }
        ],
    )

    assert record["metric_bucket"] == "absence_evidence"
    assert record["recall_applicable"] is False
    assert record["hit_at_5"] is None
    assert record["absence_applicable"] is True
    assert record["absence_hit_at_5"] is True
    assert "synthetic" in record["absence_evidence_terms"]
    assert record["coverage_status"] == "absent_evidence"
    assert record["missing_required_markers"] == [
        "QPACK_KOL_LINYA_001",
        "QPACK_KOL_MIMO_001",
    ]


def test_q027_negative_absent_still_requires_concrete_sop_evidence():
    record = build_search_diagnostic_record(
        {
            "question_id": "Q027",
            "category": "negative_absent",
            "question": "资料里是否允许客服诊断用户皮肤疾病？",
        },
        {
            "question_id": "Q027",
            "category": "negative_absent",
            "expected_answer": "不允许客服诊断皮肤疾病，只能建议暂停使用、提供批号和照片并避免医疗建议",
            "required_fact_ids": ["F_SERVICE_002", "F_CONTENT_007"],
            "expected_source_markers": ["QPACK_SERVICE_002", "QPACK_CONTENT_007"],
        },
        [
            {
                "content": "fact_id=F_INV_006 | marker=QPACK_INV_EAST_006 | 缺货替代方案",
                "metadata": {"fact_ids": ["F_INV_006"], "markers": ["QPACK_INV_EAST_006"]},
            },
            {
                "content": "fact_id=F_RULE_002 | marker=QPACK_RULE_002 | 可说帮助维持肌肤屏障",
                "metadata": {"fact_ids": ["F_RULE_002"], "markers": ["QPACK_RULE_002"]},
            },
        ],
    )

    assert record["metric_bucket"] == "fact_recall"
    assert record["recall_applicable"] is True
    assert record["absence_applicable"] is False
    assert record["hit_at_5"] is False
    assert record["all_required_hit_at_5"] is False
    assert record["coverage_status"] == "miss"
    assert record["missing_required_fact_ids"] == ["F_SERVICE_002", "F_CONTENT_007"]
    assert record["missing_required_markers"] == ["QPACK_SERVICE_002", "QPACK_CONTENT_007"]


def test_multi_file_partial_coverage_is_separate_from_fact_recall():
    record = build_search_diagnostic_record(
        {"question_id": "Q015", "category": "multi_file_synthesis", "question": "price?"},
        {
            "question_id": "Q015",
            "category": "multi_file_synthesis",
            "required_fact_ids": ["F_PROMO_002", "F_UPDATE_001", "F_UPDATE_008"],
            "expected_source_markers": ["QPACK_UPDATE_001", "QPACK_UPDATE_008"],
        },
        [
            {
                "content": "fact_id=F_UPDATE_001 | marker=QPACK_UPDATE_001 | 价格更新为249元",
                "metadata": {"fact_ids": ["F_UPDATE_001"], "markers": ["QPACK_UPDATE_001"]},
            }
        ],
    )

    assert record["metric_bucket"] == "multi_file_coverage"
    assert record["recall_applicable"] is False
    assert record["hit_at_5"] is None
    assert record["any_required_hit_at_5"] is True
    assert record["all_required_hit_at_5"] is False
    assert record["partial_required_hit_at_5"] is True
    assert record["coverage_status"] == "partial"
    assert record["missing_required_fact_ids"] == ["F_PROMO_002", "F_UPDATE_008"]
    assert record["missing_required_markers"] == ["QPACK_UPDATE_008"]


def test_diagnostics_writer_defaults_to_temp_and_not_repository(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    record = build_search_diagnostic_record(
        {"question_id": "Q001", "category": "single_file_fact", "question": "price?"},
        {"question_id": "Q001", "required_fact_ids": ["F1"], "required_markers": ["M1"]},
        [{"content": "fact_id=F1 marker=M1", "metadata": {"fact_ids": ["F1"], "markers": ["M1"]}}],
    )

    path = write_search_diagnostics_jsonl([record])
    assert path == tmp_path / "agentx-2c-rag-quality-pack" / "search_top5_diagnostics.jsonl"
    assert path.exists()
    assert not path.is_relative_to(Path.cwd())
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["question_id"] == "Q001"
    assert saved["top5"][0]["rank"] == 1
