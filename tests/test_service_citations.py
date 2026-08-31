"""Direct service-boundary tests for generated citation integrity."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from cloud_tutor.config import Settings
from cloud_tutor.models import (
    ChatRequest,
    ChatResponse,
    ChatTurn,
    KnowledgeChunk,
    RetrievedChunk,
)
from cloud_tutor.service import (
    ATTRIBUTION_FAILURE_ANSWER,
    RagService,
    numeric_citation_markers,
)


class _FakeRetriever:
    strategy = "fake-ranked-retrieval"

    def __init__(self, results: list[RetrievedChunk]) -> None:
        self.results = results
        self.last_query: str | None = None
        self.last_top_k: int | None = None

    async def search(self, query: str, top_k: int) -> list[RetrievedChunk]:
        self.last_query = query
        self.last_top_k = top_k
        return self.results[:top_k]

    async def readiness(self) -> tuple[bool, str]:
        return True, "fake retriever ready"


@dataclass
class _FakeGenerator:
    answer: str

    async def generate(
        self,
        *,
        message: str,
        query: str,
        history: list[ChatTurn],
        sources: list[RetrievedChunk],
    ) -> str:
        del message, query, history, sources
        return self.answer

    async def readiness(self) -> tuple[bool, str]:
        return True, "fake generator ready"


def _source(identifier: str, title: str, score: float = 0.9) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=KnowledgeChunk(
            id=identifier,
            title=title,
            section="Test section",
            content=f"Grounded content for {title}.",
            uri=f"https://example.com/{identifier}",
        ),
        score=score,
        keyword_score=score,
    )


def _run(answer: str, sources: list[RetrievedChunk]) -> ChatResponse:
    service = RagService(
        settings=Settings(_env_file=None, mode="demo", environment="test"),
        retriever=_FakeRetriever(sources),
        generator=_FakeGenerator(answer),
    )
    return asyncio.run(service.chat(ChatRequest(message="test question", top_k=4), "citation-test"))


def test_subset_marker_exposes_only_the_actually_cited_source() -> None:
    response = _run(
        "Only the second result supports this statement [2].",
        [_source("first", "First source"), _source("second", "Second source")],
    )

    assert response.answer.endswith("[2].")
    assert [citation.id for citation in response.citations] == ["2"]
    assert [citation.title for citation in response.citations] == ["Second source"]
    assert [item.id for item in response.trace.retrieved_documents] == ["first", "second"]


def test_citation_order_follows_first_marker_use_and_deduplicates() -> None:
    response = _run(
        "Second claim [2], first claim [1], and second again [2].",
        [_source("first", "First source"), _source("second", "Second source")],
    )

    assert [citation.id for citation in response.citations] == ["2", "1"]


@pytest.mark.parametrize(
    "answer",
    [
        "A source-backed claim with no marker.",
        "A claim with an orphan marker [3].",
        "A mixed claim with one valid marker [1] and one orphan [99].",
        "A marker cannot use the zero position [0].",
    ],
)
def test_invalid_source_attribution_fails_closed(answer: str) -> None:
    response = _run(answer, [_source("first", "First"), _source("second", "Second")])

    assert response.answer == ATTRIBUTION_FAILURE_ANSWER
    assert response.citations == []
    assert response.trace.confidence == 0
    assert len(response.trace.retrieved_documents) == 2


def test_marker_without_any_retrieved_source_fails_closed() -> None:
    response = _run("Unsupported source marker [1].", [])

    assert response.answer == ATTRIBUTION_FAILURE_ANSWER
    assert response.citations == []
    assert response.trace.confidence == 0


def test_source_free_abstention_is_preserved() -> None:
    abstention = "I could not find enough support in the knowledge base."

    response = _run(abstention, [])

    assert response.answer == abstention
    assert response.citations == []


def test_numeric_marker_parser_preserves_occurrences() -> None:
    assert numeric_citation_markers("Claims [2], [1], [2], plus [not-a-citation].") == [2, 1, 2]
