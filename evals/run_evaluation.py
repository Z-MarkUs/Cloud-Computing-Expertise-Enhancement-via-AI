"""Run deterministic retrieval and grounding quality gates.

Usage::

    python -m evals.run_evaluation
    python -m evals.run_evaluation --json-output work/eval-results.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from cloud_tutor.config import Settings
from cloud_tutor.models import ChatRequest, ChatTurn
from cloud_tutor.providers.factory import build_service
from cloud_tutor.service import numeric_citation_markers

DEFAULT_DATASET = Path(__file__).with_name("questions.json")


@dataclass(frozen=True, slots=True)
class CaseResult:
    """Inspectable outcome for one evaluation case."""

    id: str
    passed: bool
    expected_sources: list[str]
    allowed_sources: list[str]
    retrieved_sources: list[str]
    cited_source_ids: list[str]
    irrelevant_cited_source_ids: list[str]
    reciprocal_rank: float
    citations_valid: bool
    citation_marker_count: int
    citation_coverage: float
    source_precision: float
    required_terms_present: bool
    abstained: bool
    confidence: float
    latency_ms: float


def load_cases(path: Path) -> list[dict[str, Any]]:
    """Load and minimally validate evaluation cases."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Evaluation dataset must contain a non-empty cases array")
    return cases


async def evaluate_case(service: Any, case: dict[str, Any]) -> CaseResult:
    """Evaluate retrieval, citation integrity, key terms, and abstention."""
    started = time.perf_counter()
    history = [ChatTurn.model_validate(turn) for turn in case.get("history", [])]
    response = await service.chat(
        ChatRequest(
            message=case["question"],
            history=history,
            top_k=case.get("top_k"),
        ),
        request_id=f"eval-{uuid.uuid4()}",
    )
    latency_ms = (time.perf_counter() - started) * 1_000
    retrieved = [document.id for document in response.trace.retrieved_documents]
    expected = [str(source) for source in case.get("expected_sources", [])]
    allowed = list(
        dict.fromkeys(expected + [str(source) for source in case.get("allowed_sources", [])])
    )
    ranks = [retrieved.index(source) + 1 for source in expected if source in retrieved]
    reciprocal_rank = 1.0 / min(ranks) if ranks else 0.0

    marker_positions = numeric_citation_markers(response.answer)
    unique_positions = list(dict.fromkeys(marker_positions))
    positions_in_range = all(1 <= position <= len(retrieved) for position in marker_positions)
    try:
        response_citation_positions = [int(citation.id) for citation in response.citations]
    except ValueError:
        response_citation_positions = []
        positions_in_range = False
    cited_source_ids = [
        retrieved[position - 1] for position in unique_positions if 1 <= position <= len(retrieved)
    ]
    citation_marker_parity = (
        bool(marker_positions)
        and bool(response.citations)
        and positions_in_range
        and len(response_citation_positions) == len(set(response_citation_positions))
        and set(response_citation_positions) == set(unique_positions)
    )
    citations_valid = citation_marker_parity
    citation_coverage = (
        len(set(expected) & set(cited_source_ids)) / len(set(expected)) if expected else 1.0
    )
    irrelevant_cited_source_ids = [
        source for source in cited_source_ids if source not in set(allowed)
    ]
    source_precision = (
        (len(cited_source_ids) - len(irrelevant_cited_source_ids)) / len(cited_source_ids)
        if cited_source_ids
        else (1.0 if case.get("expect_abstention") else 0.0)
    )
    required = [term.casefold() for term in case.get("required_terms", [])]
    answer_lower = response.answer.casefold()
    required_terms_present = all(term in answer_lower for term in required)
    abstained = (
        not response.citations
        and not marker_positions
        and (
            "could not find enough support" in answer_lower
            or "could not provide a safely attributable answer" in answer_lower
        )
    )
    expect_abstention = bool(case.get("expect_abstention", False))
    if expect_abstention:
        passed = abstained
    else:
        minimum_coverage = float(case.get("minimum_citation_coverage", 1.0))
        minimum_source_precision = float(case.get("minimum_source_precision", 1.0))
        passed = (
            bool(ranks)
            and citations_valid
            and citation_coverage >= minimum_coverage
            and source_precision >= minimum_source_precision
            and required_terms_present
        )
    return CaseResult(
        id=str(case["id"]),
        passed=passed,
        expected_sources=expected,
        allowed_sources=allowed,
        retrieved_sources=retrieved,
        cited_source_ids=cited_source_ids,
        irrelevant_cited_source_ids=irrelevant_cited_source_ids,
        reciprocal_rank=round(reciprocal_rank, 4),
        citations_valid=citations_valid,
        citation_marker_count=len(marker_positions),
        citation_coverage=round(citation_coverage, 4),
        source_precision=round(source_precision, 4),
        required_terms_present=required_terms_present,
        abstained=abstained,
        confidence=response.trace.confidence,
        latency_ms=round(latency_ms, 3),
    )


async def run_evaluation(dataset: Path = DEFAULT_DATASET) -> dict[str, Any]:
    """Execute all cases and calculate quality-gate metrics."""
    settings = Settings(mode="demo", environment="test")
    service = build_service(settings)
    cases = load_cases(dataset)
    results = [await evaluate_case(service, case) for case in cases]
    answerable = [
        result
        for result, case in zip(results, cases, strict=True)
        if not case.get("expect_abstention")
    ]
    abstention = [
        result for result, case in zip(results, cases, strict=True) if case.get("expect_abstention")
    ]

    retrieval_hit_rate = (
        sum(result.reciprocal_rank > 0 for result in answerable) / len(answerable)
        if answerable
        else 0.0
    )
    mean_reciprocal_rank = (
        sum(result.reciprocal_rank for result in answerable) / len(answerable)
        if answerable
        else 0.0
    )
    citation_validity = (
        sum(result.citations_valid for result in answerable) / len(answerable)
        if answerable
        else 0.0
    )
    citation_coverage = (
        sum(result.citation_coverage for result in answerable) / len(answerable)
        if answerable
        else 0.0
    )
    source_precision = (
        sum(result.source_precision for result in answerable) / len(answerable)
        if answerable
        else 0.0
    )
    noise_free_citation_rate = (
        sum(not result.irrelevant_cited_source_ids for result in answerable) / len(answerable)
        if answerable
        else 0.0
    )
    term_coverage = (
        sum(result.required_terms_present for result in answerable) / len(answerable)
        if answerable
        else 0.0
    )
    abstention_accuracy = (
        sum(result.abstained for result in abstention) / len(abstention) if abstention else 1.0
    )
    p95_index = max(0, math_ceil(len(results) * 0.95) - 1)
    sorted_latencies = sorted(result.latency_ms for result in results)
    metrics = {
        "retrieval_hit_rate": round(retrieval_hit_rate, 4),
        "mean_reciprocal_rank": round(mean_reciprocal_rank, 4),
        "citation_validity": round(citation_validity, 4),
        "citation_coverage": round(citation_coverage, 4),
        "source_precision": round(source_precision, 4),
        "noise_free_citation_rate": round(noise_free_citation_rate, 4),
        "required_term_coverage": round(term_coverage, 4),
        "abstention_accuracy": round(abstention_accuracy, 4),
        "p95_latency_ms": sorted_latencies[p95_index],
    }
    thresholds = {
        "retrieval_hit_rate": 0.9,
        "mean_reciprocal_rank": 0.75,
        "citation_validity": 1.0,
        "citation_coverage": 0.95,
        "source_precision": 0.95,
        "noise_free_citation_rate": 0.9,
        "required_term_coverage": 0.9,
        "abstention_accuracy": 1.0,
    }
    passed = all(metrics[name] >= threshold for name, threshold in thresholds.items()) and all(
        result.passed for result in results
    )
    return {
        "passed": passed,
        "mode": "demo",
        "benchmark_type": "deterministic_regression",
        "scope_note": (
            "Committed same-corpus regression benchmark; not a held-out evaluation or "
            "evidence of live Azure quality."
        ),
        "dataset": str(dataset),
        "case_count": len(results),
        "metrics": metrics,
        "thresholds": thresholds,
        "cases": [asdict(result) for result in results],
    }


def math_ceil(value: float) -> int:
    """Integer ceiling without importing a numerical stack."""
    integer = int(value)
    return integer if integer == value else integer + 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--json-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = asyncio.run(run_evaluation(args.dataset))
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(f"{rendered}\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
