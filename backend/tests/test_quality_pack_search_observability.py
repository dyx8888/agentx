import json
import tempfile
from pathlib import Path
from typing import Any


MAX_CONTENT_EXCERPT_CHARS = 160
TOP_K_DIAGNOSTIC_LIMIT = 5


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


def build_search_diagnostic_record(
    question: dict[str, Any],
    ground_truth: dict[str, Any],
    search_results: list[dict[str, Any]],
) -> dict[str, Any]:
    required_fact_ids = _string_list(ground_truth.get("required_fact_ids"))
    required_markers = _string_list(
        ground_truth.get("required_markers")
        or ground_truth.get("expected_source_markers")
    )
    recall_applicable = bool(required_fact_ids or required_markers)

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

    return {
        "question_id": question.get("question_id") or ground_truth.get("question_id"),
        "category": question.get("category") or ground_truth.get("category"),
        "query": question.get("question", ""),
        "required_fact_ids": required_fact_ids,
        "required_markers": required_markers,
        "required_files": _string_list(ground_truth.get("required_files")),
        "recall_applicable": recall_applicable,
        "hit_at_3": None if not recall_applicable else any(rank <= 3 for rank in matched_ranks),
        "hit_at_5": None if not recall_applicable else bool(matched_ranks),
        "missing_required_fact_ids": [
            fact_id for fact_id in required_fact_ids if fact_id not in fact_rank
        ],
        "missing_required_markers": [
            marker for marker in required_markers if marker not in marker_rank
        ],
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

    assert record["hit_at_3"] is False
    assert record["hit_at_5"] is False
    assert record["missing_required_fact_ids"] == ["F_UPDATE_003"]
    assert record["missing_required_markers"] == ["QPACK_UPDATE_003"]
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
    assert record["hit_at_3"] is None
    assert record["hit_at_5"] is None
    assert record["mrr_rank"] is None
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
    assert top["chunk_type"] == "fact_line"
    assert top["section_title"] == "平台规则"
    assert top["fact_ids"] == ["F_RULE_001"]
    assert top["markers"] == ["QPACK_RULE_001"]
    assert len(top["content_excerpt"]) == MAX_CONTENT_EXCERPT_CHARS


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
