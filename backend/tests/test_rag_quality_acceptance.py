"""Local RAG quality acceptance checks using only fake in-memory components."""

from __future__ import annotations

import json
import time
from pathlib import Path


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "rag_quality_cases.json"


def _load_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _normalize(value: str) -> str:
    return " ".join(value.lower().split())


class FakeRetriever:
    """Deterministic tenant-filtered retriever; never touches vector services."""

    def __init__(self, documents):
        self.documents = documents

    def search(self, case, top_k=3):
        query_terms = [_normalize(term) for term in case.get("query_terms", [])]
        scored = []

        for document in self.documents:
            if document["company_id"] != case["company_id"]:
                continue

            haystack = _normalize(
                " ".join(
                    [
                        document["title"],
                        document["content"],
                        " ".join(document.get("keywords", [])),
                    ]
                )
            )
            score = sum(1 for term in query_terms if term in haystack)
            if score:
                scored.append((score, document))

        scored.sort(key=lambda item: (-item[0], item[1]["doc_id"]))
        return [document for _score, document in scored[:top_k]]


class FakeAnswerGenerator:
    """Grounded answer generator that only repeats fixture facts."""

    refusal = "Insufficient knowledge base evidence to answer this question."

    def answer(self, case, retrieved_docs):
        if case.get("no_answer") or not retrieved_docs:
            return {
                "answer": self.refusal,
                "citations": [],
                "refused": True,
            }

        citations = []
        for doc in retrieved_docs:
            if doc["doc_id"] in case["expected_doc_ids"]:
                citations.append(
                    {
                        "doc_id": doc["doc_id"],
                        "source_file": doc["source_file"],
                        "chunk_index": doc["chunk_index"],
                        "snippet": doc["content"],
                    }
                )

        return {
            "answer": "; ".join(case["required_facts"]),
            "citations": citations,
            "refused": False,
        }


def _rank_of_first_expected(retrieved_docs, expected_doc_ids):
    for index, doc in enumerate(retrieved_docs, start=1):
        if doc["doc_id"] in expected_doc_ids:
            return index
    return None


def _citation_supports_required_terms(case, answer_payload):
    if case.get("no_answer"):
        return True

    snippets = _normalize(
        " ".join(citation["snippet"] for citation in answer_payload["citations"])
    )
    return all(_normalize(term) in snippets for term in case["support_terms"])


def _unsupported_claims(case, answer_payload):
    answer = _normalize(answer_payload["answer"])
    return [
        claim
        for claim in case.get("forbidden_claims", [])
        if _normalize(claim) in answer
    ]


def _evaluate_quality(fixture):
    retriever = FakeRetriever(fixture["documents"])
    generator = FakeAnswerGenerator()
    retrieval_cases = [case for case in fixture["cases"] if case["expected_doc_ids"]]
    no_answer_cases = [case for case in fixture["cases"] if case.get("no_answer")]

    start = time.perf_counter()
    results = []
    for case in fixture["cases"]:
        retrieved = retriever.search(case, top_k=3)
        answer_payload = generator.answer(case, retrieved)
        results.append(
            {
                "case": case,
                "retrieved": retrieved,
                "answer": answer_payload,
            }
        )
    elapsed_ms = (time.perf_counter() - start) * 1000

    hit_count = 0
    reciprocal_ranks = []
    citation_hits = 0
    citation_total = 0
    refusal_hits = 0
    cross_company_leaks = 0
    unsupported_claims = 0

    for result in results:
        case = result["case"]
        retrieved = result["retrieved"]
        answer_payload = result["answer"]
        expected_doc_ids = case["expected_doc_ids"]

        if expected_doc_ids:
            retrieved_doc_ids = [doc["doc_id"] for doc in retrieved]
            if any(doc_id in retrieved_doc_ids[:3] for doc_id in expected_doc_ids):
                hit_count += 1

            rank = _rank_of_first_expected(retrieved, expected_doc_ids)
            reciprocal_ranks.append(0 if rank is None else 1 / rank)

            citation_total += 1
            if _citation_supports_required_terms(case, answer_payload):
                citation_hits += 1

        if case.get("no_answer") and answer_payload["refused"]:
            refusal_hits += 1

        forbidden_doc_ids = set(case.get("forbidden_doc_ids", []))
        for doc in retrieved:
            if doc["company_id"] != case["company_id"] or doc["doc_id"] in forbidden_doc_ids:
                cross_company_leaks += 1

        for citation in answer_payload["citations"]:
            doc = next(doc for doc in fixture["documents"] if doc["doc_id"] == citation["doc_id"])
            if doc["company_id"] != case["company_id"] or doc["doc_id"] in forbidden_doc_ids:
                cross_company_leaks += 1

        unsupported_claims += len(_unsupported_claims(case, answer_payload))

    return {
        "hit_at_3": hit_count / len(retrieval_cases),
        "mrr": sum(reciprocal_ranks) / len(reciprocal_ranks),
        "citation_hit_rate": citation_hits / citation_total,
        "refusal_rate": refusal_hits / len(no_answer_cases),
        "cross_company_leaks": cross_company_leaks,
        "unsupported_claims": unsupported_claims,
        "latency_ms": elapsed_ms,
        "results": results,
    }


def test_rag_quality_acceptance_metrics_pass_thresholds():
    fixture = _load_fixture()
    metrics = _evaluate_quality(fixture)
    thresholds = fixture["thresholds"]

    assert metrics["hit_at_3"] >= thresholds["hit_at_3"], metrics
    assert metrics["mrr"] >= thresholds["mrr"], metrics
    assert metrics["citation_hit_rate"] >= thresholds["citation_hit_rate"], metrics
    assert metrics["refusal_rate"] >= thresholds["refusal_rate"], metrics
    assert metrics["cross_company_leaks"] == thresholds["cross_company_leaks"], metrics
    assert metrics["unsupported_claims"] == thresholds["unsupported_claims"], metrics
    assert metrics["latency_ms"] <= thresholds["max_latency_ms"], metrics


def test_required_facts_are_present_and_supported_by_citations():
    fixture = _load_fixture()
    metrics = _evaluate_quality(fixture)

    for result in metrics["results"]:
        case = result["case"]
        answer_payload = result["answer"]
        if case.get("no_answer"):
            continue

        answer = _normalize(answer_payload["answer"])
        assert all(_normalize(fact) in answer for fact in case["required_facts"])
        assert answer_payload["citations"]
        assert _citation_supports_required_terms(case, answer_payload)


def test_no_answer_case_refuses_without_fabricated_specifics():
    fixture = _load_fixture()
    metrics = _evaluate_quality(fixture)

    no_answer_results = [
        result for result in metrics["results"] if result["case"].get("no_answer")
    ]
    assert no_answer_results

    for result in no_answer_results:
        answer_payload = result["answer"]
        assert answer_payload["refused"] is True
        assert answer_payload["citations"] == []
        assert _unsupported_claims(result["case"], answer_payload) == []


def test_company_id_isolation_blocks_cross_tenant_docs_and_claims():
    fixture = _load_fixture()
    metrics = _evaluate_quality(fixture)

    isolation = next(
        result
        for result in metrics["results"]
        if result["case"]["case_id"] == "company_a_tenant_isolation"
    )
    retrieved_doc_ids = [doc["doc_id"] for doc in isolation["retrieved"]]

    assert "company_a_ads_q2" in retrieved_doc_ids
    assert "company_b_ads_q2" not in retrieved_doc_ids
    assert "72 yuan" not in isolation["answer"]["answer"]
    assert metrics["cross_company_leaks"] == 0


def test_unsupported_claim_detector_rejects_known_forbidden_claims():
    case = {
        "forbidden_claims": ["72 yuan", "hospital endorsement"],
    }
    answer_payload = {
        "answer": "The CPA target is 72 yuan with hospital endorsement.",
        "citations": [],
        "refused": False,
    }

    assert _unsupported_claims(case, answer_payload) == [
        "72 yuan",
        "hospital endorsement",
    ]
