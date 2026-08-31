"""Unit tests for local corpus validation, retrieval, and grounded generation."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from cloud_tutor.errors import CorpusError
from cloud_tutor.models import ChatTurn
from cloud_tutor.providers.demo import DemoAnswerGenerator, DemoRetriever, tokenize
from cloud_tutor.service import ConversationQueryPlanner


def test_tokenize_normalizes_and_removes_stop_words() -> None:
    assert tokenize("What is CI/CD for a CLOUD-native app?") == [
        "ci",
        "cd",
        "cloud-native",
        "app",
    ]


@pytest.mark.parametrize(
    ("query", "expected_id"),
    [
        ("Explain virtual machine infrastructure service models", "cloud-service-models"),
        ("How should I protect a credential in a vault?", "encryption-secrets"),
        ("How does autoscaling elasticity work?", "scalability-elasticity"),
        ("What is an SLO error budget?", "sre-objectives"),
        ("Compare block, object, and file storage", "storage-types"),
    ],
)
def test_retriever_ranks_expected_cloud_concept_first(
    corpus_path: Path, query: str, expected_id: str
) -> None:
    retriever = DemoRetriever(corpus_path)

    results = asyncio.run(retriever.search(query, top_k=4))

    assert results[0].chunk.id == expected_id
    assert 0 < results[0].score <= 1
    assert results[0].keyword_score == results[0].score


def test_retrieval_is_deterministic_and_honors_top_k(corpus_path: Path) -> None:
    retriever = DemoRetriever(corpus_path)

    first = asyncio.run(retriever.search("cloud reliability zones", top_k=2))
    second = asyncio.run(retriever.search("cloud reliability zones", top_k=2))

    assert first == second
    assert len(first) <= 2


def test_relative_cutoff_preserves_genuinely_related_service_model_sources(
    corpus_path: Path,
) -> None:
    retriever = DemoRetriever(corpus_path)

    results = asyncio.run(retriever.search("How do IaaS, PaaS, and SaaS differ?", top_k=4))

    assert [result.chunk.id for result in results] == [
        "cloud-service-models",
        "shared-responsibility",
    ]


def test_out_of_domain_query_returns_no_results(corpus_path: Path) -> None:
    retriever = DemoRetriever(corpus_path)

    results = asyncio.run(retriever.search("xylophonic quasar zebrafish", top_k=4))

    assert results == []


def test_demo_generator_places_marker_on_every_source(corpus_path: Path) -> None:
    retriever = DemoRetriever(corpus_path)
    generator = DemoAnswerGenerator()
    results = asyncio.run(retriever.search("RPO and RTO", top_k=3))

    answer = asyncio.run(
        generator.generate(
            message="RPO and RTO?",
            query="RPO and RTO?",
            history=[],
            sources=results,
        )
    )

    assert all(f"[{index}]" in answer for index in range(1, len(results) + 1))
    assert "source-grounded" in answer


def test_query_planner_keeps_standalone_questions_unchanged() -> None:
    history = [ChatTurn(role="user", content="Explain storage")]

    query = ConversationQueryPlanner.plan(
        "How do availability zones isolate datacenter failures?", history
    )

    assert query == "How do availability zones isolate datacenter failures?"


def test_query_planner_expands_pronoun_follow_up() -> None:
    history = [
        ChatTurn(role="user", content="Compare queues and streams"),
        ChatTurn(role="assistant", content="They have different consumption models"),
    ]

    query = ConversationQueryPlanner.plan("When should I use them?", history)

    assert query == "Compare queues and streams | Follow-up: When should I use them?"


def test_corpus_rejects_duplicate_ids(tmp_path: Path) -> None:
    corpus = tmp_path / "duplicate.json"
    document = {
        "id": "same",
        "title": "Title",
        "section": "Section",
        "content": "Content",
        "tags": [],
        "uri": "https://example.com",
    }
    corpus.write_text(json.dumps({"documents": [document, document]}), encoding="utf-8")

    with pytest.raises(CorpusError, match="Duplicate"):
        DemoRetriever(corpus)


@pytest.fixture
def corpus_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "cloud_knowledge.json"
