"""Quality-gate tests for the committed offline evaluation set."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from cloud_tutor.models import (
    ChatRequest,
    ChatResponse,
    Citation,
    RetrievedDocumentTrace,
    TraceMetadata,
)
from evals.run_evaluation import evaluate_case, load_cases, run_evaluation


class _ResponseService:
    def __init__(self, response: ChatResponse) -> None:
        self.response = response
        self.request: ChatRequest | None = None

    async def chat(self, request: ChatRequest, request_id: str) -> ChatResponse:
        del request_id
        self.request = request
        return self.response


def _response(
    *,
    answer: str,
    retrieved_ids: list[str],
    citation_positions: list[int],
) -> ChatResponse:
    return ChatResponse(
        answer=answer,
        citations=[
            Citation(
                id=str(position),
                title=f"Source {position}",
                section="Test",
                excerpt="Supported text.",
                score=0.9,
                uri=None,
            )
            for position in citation_positions
        ],
        trace=TraceMetadata(
            request_id="evaluation-test",
            mode="demo",
            retrieval_ms=1,
            generation_ms=1,
            total_ms=2,
            query="test",
            confidence=0.9,
            retrieval_strategy="fake",
            retrieved_documents=[
                RetrievedDocumentTrace(id=identifier, title=identifier, score=0.9)
                for identifier in retrieved_ids
            ],
        ),
    )


def test_evaluation_dataset_has_answerable_and_abstention_cases() -> None:
    path = Path(__file__).resolve().parents[1] / "evals" / "questions.json"

    cases = load_cases(path)

    assert len(cases) >= 50
    assert sum(bool(case.get("expect_abstention")) for case in cases) >= 8
    assert all(case.get("id") and case.get("question") for case in cases)

    kinds = {case.get("kind") for case in cases}
    assert {"direct", "paraphrase", "ambiguous", "near-domain", "prompt-injection"} <= kinds

    corpus_path = Path(__file__).resolve().parents[1] / "data" / "cloud_knowledge.json"
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    corpus_ids = {document["id"] for document in corpus["documents"]}
    benchmark_source_ids = {source for case in cases for source in case.get("expected_sources", [])}
    assert corpus_ids <= benchmark_source_ids


def test_offline_quality_gates_pass() -> None:
    report = asyncio.run(run_evaluation())

    assert report["passed"] is True
    assert report["metrics"]["retrieval_hit_rate"] >= 0.9
    assert report["metrics"]["mean_reciprocal_rank"] >= 0.75
    assert report["metrics"]["citation_validity"] == 1.0
    assert report["metrics"]["citation_coverage"] >= 0.95
    assert report["metrics"]["source_precision"] >= 0.95
    assert report["metrics"]["noise_free_citation_rate"] >= 0.9
    assert report["metrics"]["abstention_accuracy"] == 1.0
    assert all(case["passed"] for case in report["cases"])
    assert report["benchmark_type"] == "deterministic_regression"
    assert "not a held-out evaluation" in report["scope_note"]


def test_answerable_case_cannot_pass_with_vacuous_empty_citations() -> None:
    service = _ResponseService(
        _response(answer="An uncited answer.", retrieved_ids=["expected"], citation_positions=[])
    )

    result = asyncio.run(
        evaluate_case(
            service,
            {
                "id": "empty-citations",
                "question": "Question",
                "expected_sources": ["expected"],
                "required_terms": ["answer"],
            },
        )
    )

    assert result.citations_valid is False
    assert result.citation_marker_count == 0
    assert result.citation_coverage == 0
    assert result.source_precision == 0
    assert result.passed is False


def test_evaluation_maps_subset_marker_position_to_retrieved_source_id() -> None:
    service = _ResponseService(
        _response(
            answer="The supported claim is here [2].",
            retrieved_ids=["distractor", "expected"],
            citation_positions=[2],
        )
    )

    result = asyncio.run(
        evaluate_case(
            service,
            {
                "id": "subset",
                "question": "Question",
                "expected_sources": ["expected"],
                "required_terms": ["supported"],
                "history": [
                    {"role": "user", "content": "Earlier question"},
                    {"role": "assistant", "content": "Earlier answer"},
                ],
            },
        )
    )

    assert result.cited_source_ids == ["expected"]
    assert result.citation_coverage == 1
    assert result.source_precision == 1
    assert result.irrelevant_cited_source_ids == []
    assert result.citations_valid is True
    assert result.passed is True
    assert service.request is not None
    assert len(service.request.history) == 2


def test_evaluation_flags_cited_sources_outside_the_allowed_set() -> None:
    service = _ResponseService(
        _response(
            answer="A relevant claim [2] plus a noisy tail [1].",
            retrieved_ids=["noise", "expected"],
            citation_positions=[2, 1],
        )
    )

    result = asyncio.run(
        evaluate_case(
            service,
            {
                "id": "precision-regression",
                "question": "Question",
                "expected_sources": ["expected"],
                "allowed_sources": [],
                "required_terms": ["relevant"],
            },
        )
    )

    assert result.cited_source_ids == ["expected", "noise"]
    assert result.irrelevant_cited_source_ids == ["noise"]
    assert result.source_precision == 0.5
    assert result.passed is False
