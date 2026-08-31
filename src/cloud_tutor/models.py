"""Public API schemas and internal retrieval records."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class StrictModel(BaseModel):
    """Base model that rejects misspelled or unexpected request fields."""

    model_config = ConfigDict(extra="forbid")


class ChatTurn(StrictModel):
    """One prior user or assistant message supplied for conversational context."""

    role: Literal["user", "assistant"]
    content: NonEmptyText = Field(max_length=32_000)


class ChatRequest(StrictModel):
    """A grounded chat request."""

    message: NonEmptyText = Field(max_length=32_000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=100)
    top_k: int | None = Field(default=None, ge=1, le=20)

    @field_validator("history")
    @classmethod
    def history_must_alternate(cls, history: list[ChatTurn]) -> list[ChatTurn]:
        for previous, current in pairwise(history):
            if previous.role == current.role:
                raise ValueError("history roles must alternate between user and assistant")
        return history


class Citation(StrictModel):
    """A source passage used to support the generated answer."""

    id: str
    title: str
    section: str
    excerpt: str
    score: float = Field(ge=0.0, le=1.0)
    uri: str | None = None


class RetrievedDocumentTrace(StrictModel):
    """Retrieval score summary safe to expose to clients."""

    id: str
    title: str
    score: float = Field(ge=0.0, le=1.0)
    keyword_score: float | None = Field(default=None, ge=0.0, le=1.0)
    vector_score: float | None = Field(default=None, ge=0.0, le=1.0)


class TraceMetadata(StrictModel):
    """Latency, mode, query, and retrieval observability for one request."""

    request_id: str
    mode: Literal["demo", "azure"]
    retrieval_ms: float = Field(ge=0.0)
    generation_ms: float = Field(ge=0.0)
    total_ms: float = Field(ge=0.0)
    query: str
    confidence: float = Field(ge=0.0, le=1.0)
    retrieval_strategy: str
    retrieved_documents: list[RetrievedDocumentTrace]


class ChatResponse(StrictModel):
    """Stable response contract consumed by the browser experience."""

    answer: str
    citations: list[Citation]
    trace: TraceMetadata


class PublicConfig(StrictModel):
    """Non-secret capabilities clients may use to configure their UI."""

    app_name: str
    version: str
    mode: Literal["demo", "azure"]
    environment: str
    model: str
    retrieval_strategy: str
    default_top_k: int
    max_top_k: int
    max_message_chars: int
    max_history_turns: int
    authentication_required: bool
    features: list[str]


class HealthResponse(StrictModel):
    """Health endpoint payload."""

    status: Literal["ok", "ready", "not_ready"]
    mode: Literal["demo", "azure"]
    version: str
    checks: dict[str, str] = Field(default_factory=dict)


class ErrorDetail(StrictModel):
    """Safe machine-readable error details."""

    code: str
    message: str
    request_id: str
    details: list[dict[str, str]] | None = None


class ErrorResponse(StrictModel):
    """Stable envelope for validation, auth, and provider errors."""

    error: ErrorDetail


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    """A normalized corpus record."""

    id: str
    title: str
    section: str
    content: str
    uri: str | None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A corpus record plus normalized retrieval scores."""

    chunk: KnowledgeChunk
    score: float
    keyword_score: float | None = None
    vector_score: float | None = None
    metadata: dict[str, str] = field(default_factory=dict)
