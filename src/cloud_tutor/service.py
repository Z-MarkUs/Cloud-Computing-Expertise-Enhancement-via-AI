"""Conversation-aware retrieval-augmented generation orchestration."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from cloud_tutor.config import Settings
from cloud_tutor.models import (
    ChatRequest,
    ChatResponse,
    ChatTurn,
    Citation,
    RetrievedChunk,
    RetrievedDocumentTrace,
    TraceMetadata,
)
from cloud_tutor.providers.base import AnswerGenerator, Retriever
from cloud_tutor.providers.demo import tokenize

FOLLOW_UP_TERMS = frozenset(
    {
        "it",
        "its",
        "that",
        "those",
        "they",
        "them",
        "this",
        "these",
        "former",
        "latter",
    }
)
CITATION_MARKER_PATTERN = re.compile(r"\[(\d+)\]")
ATTRIBUTION_FAILURE_ANSWER = (
    "I could not provide a safely attributable answer because the generated response "
    "did not reference the retrieved sources correctly. Please try again or rephrase "
    "the question."
)


class ConversationQueryPlanner:
    """Resolve compact follow-ups without an LLM or hidden conversation state."""

    @staticmethod
    def plan(message: str, history: list[ChatTurn]) -> str:
        clean_message = " ".join(message.split())
        if not history:
            return clean_message

        tokens = set(tokenize(clean_message, remove_stop_words=False))
        is_follow_up = bool(tokens & FOLLOW_UP_TERMS) or len(tokens) <= 5
        if not is_follow_up:
            return clean_message

        previous_user = next(
            (turn.content for turn in reversed(history) if turn.role == "user"),
            None,
        )
        if not previous_user:
            return clean_message
        previous_user = " ".join(str(previous_user).split())
        return f"{previous_user} | Follow-up: {clean_message}"


def _confidence(results: list[RetrievedChunk]) -> float:
    if not results:
        return 0.0
    top = results[0].score
    supporting = sum(result.score for result in results[1:3]) / max(1, min(2, len(results) - 1))
    score = top * 0.78 + supporting * 0.22
    return round(min(1.0, max(0.0, score)), 3)


def _excerpt(content: str, query: str, limit: int = 320) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", content)
    query_tokens = set(tokenize(query))
    best = max(
        (sentence.strip() for sentence in sentences if sentence.strip()),
        key=lambda sentence: len(set(tokenize(sentence)) & query_tokens),
        default=content,
    )
    if len(best) <= limit:
        return best
    return f"{best[: limit - 1].rsplit(' ', 1)[0]}…"


def numeric_citation_markers(answer: str) -> list[int]:
    """Return numeric citation positions in their original order, including duplicates."""
    return [int(marker) for marker in CITATION_MARKER_PATTERN.findall(answer)]


def _validated_citation_positions(answer: str, source_count: int) -> list[int] | None:
    """Validate citation markers and return unique positions in first-use order.

    ``None`` means attribution failed. An answer backed by retrieved sources must
    contain at least one marker, and every marker must reference an available
    source. Answers generated without sources must contain no source markers.
    """
    markers = numeric_citation_markers(answer)
    if not markers:
        return [] if source_count == 0 else None
    if any(position < 1 or position > source_count for position in markers):
        return None
    return list(dict.fromkeys(markers))


@dataclass(slots=True)
class RagService:
    """Coordinate query planning, retrieval, generation, and trace creation."""

    settings: Settings
    retriever: Retriever
    generator: AnswerGenerator

    async def chat(self, request: ChatRequest, request_id: str) -> ChatResponse:
        started = time.perf_counter()
        query = ConversationQueryPlanner.plan(request.message, request.history)
        top_k = request.top_k or self.settings.default_top_k

        retrieval_started = time.perf_counter()
        retrieved = await self.retriever.search(query, top_k)
        retrieval_ms = (time.perf_counter() - retrieval_started) * 1_000
        confidence = _confidence(retrieved)
        grounded_sources = (
            retrieved if retrieved and confidence >= self.settings.minimum_confidence else []
        )

        generation_started = time.perf_counter()
        answer = await self.generator.generate(
            message=request.message,
            query=query,
            history=request.history,
            sources=grounded_sources,
        )
        generation_ms = (time.perf_counter() - generation_started) * 1_000

        cited_positions = _validated_citation_positions(answer, len(grounded_sources))
        if cited_positions is None:
            answer = ATTRIBUTION_FAILURE_ANSWER
            cited_positions = []
            confidence = 0.0

        citations: list[Citation] = []
        for position in cited_positions:
            result = grounded_sources[position - 1]
            citations.append(
                Citation(
                    id=str(position),
                    title=result.chunk.title,
                    section=result.chunk.section,
                    excerpt=_excerpt(result.chunk.content, query),
                    score=result.score,
                    uri=result.chunk.uri,
                )
            )
        total_ms = (time.perf_counter() - started) * 1_000
        trace = TraceMetadata(
            request_id=request_id,
            mode=self.settings.mode,
            retrieval_ms=round(retrieval_ms, 3),
            generation_ms=round(generation_ms, 3),
            total_ms=round(total_ms, 3),
            query=query,
            confidence=confidence,
            retrieval_strategy=self.retriever.strategy,
            retrieved_documents=[
                RetrievedDocumentTrace(
                    id=result.chunk.id,
                    title=result.chunk.title,
                    score=result.score,
                    keyword_score=result.keyword_score,
                    vector_score=result.vector_score,
                )
                for result in retrieved
            ],
        )
        return ChatResponse(answer=answer, citations=citations, trace=trace)

    async def readiness(self) -> tuple[bool, dict[str, str]]:
        retrieval_ready, retrieval_detail = await self.retriever.readiness()
        generation_ready, generation_detail = await self.generator.readiness()
        return retrieval_ready and generation_ready, {
            "retriever": retrieval_detail,
            "generator": generation_detail,
        }
