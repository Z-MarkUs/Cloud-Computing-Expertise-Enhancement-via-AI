"""Deterministic, dependency-light retrieval and generation for local demos."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cloud_tutor.errors import CorpusError
from cloud_tutor.models import ChatTurn, KnowledgeChunk, RetrievedChunk

TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")
SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")

STOP_WORDS = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "can",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "should",
        "that",
        "the",
        "their",
        "these",
        "this",
        "to",
        "us",
        "what",
        "when",
        "which",
        "why",
        "with",
        "would",
        "you",
    }
)

CONCEPT_GROUPS = (
    ("iaas", "infrastructure", "virtual machine", "vm"),
    ("paas", "platform", "managed runtime"),
    ("saas", "software service"),
    ("identity", "iam", "rbac", "access"),
    ("availability", "reliability", "high availability", "ha"),
    ("disaster recovery", "dr", "recovery", "rpo", "rto"),
    ("scale", "scaling", "scalability", "autoscaling", "elasticity"),
    ("observability", "monitoring", "telemetry", "logs", "metrics", "traces"),
    ("infrastructure as code", "iac", "terraform", "bicep", "cloudformation"),
    ("continuous integration", "ci", "continuous delivery", "cd", "pipeline"),
    ("container", "containers", "docker", "kubernetes", "orchestration"),
    ("serverless", "function", "faas"),
    ("vpc", "vnet", "virtual network", "subnet", "networking"),
    ("queue", "queues", "messaging", "message broker", "pubsub"),
    ("cost", "finops", "budget", "rightsizing"),
    ("secret", "credential", "password", "token", "key vault"),
)

TOKEN_ALIASES = {
    "horizontally": "horizontal",
    "vertically": "vertical",
    "probes": "probe",
    "retries": "retry",
    "scales": "scale",
}

# Require both meaningful absolute evidence and a score close to the best hit.
# The relative floor prevents a common query token from pulling a long, weak
# evidence tail into an otherwise focused answer.
ABSOLUTE_RELEVANCE_FLOOR = 0.75
RELATIVE_RELEVANCE_FLOOR = 0.56


def tokenize(text: str, *, remove_stop_words: bool = True) -> list[str]:
    """Normalize text into deterministic ASCII search tokens."""
    tokens = [TOKEN_ALIASES.get(token, token) for token in TOKEN_PATTERN.findall(text.casefold())]
    if remove_stop_words:
        return [token for token in tokens if token not in STOP_WORDS and len(token) > 1]
    return tokens


def _concept_expansions(query: str) -> list[str]:
    query_lower = query.casefold()
    query_tokens = set(tokenize(query, remove_stop_words=False))
    expanded: list[str] = []
    for group in CONCEPT_GROUPS:
        if any(term in query_lower if " " in term else term in query_tokens for term in group):
            expanded.extend(group)
    return expanded


def _load_chunks(path: Path) -> list[KnowledgeChunk]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CorpusError(f"Could not read corpus at {path}") from error

    documents = raw.get("documents") if isinstance(raw, dict) else None
    if not isinstance(documents, list) or not documents:
        raise CorpusError("Corpus must contain a non-empty documents array")

    chunks: list[KnowledgeChunk] = []
    seen_ids: set[str] = set()
    for index, document in enumerate(documents):
        if not isinstance(document, dict):
            raise CorpusError(f"Corpus document {index} must be an object")
        required = ("id", "title", "section", "content")
        if any(
            not isinstance(document.get(field), str) or not document[field].strip()
            for field in required
        ):
            raise CorpusError(f"Corpus document {index} is missing a required text field")
        document_id = document["id"].strip()
        if document_id in seen_ids:
            raise CorpusError(f"Duplicate corpus document id: {document_id}")
        seen_ids.add(document_id)

        raw_tags = document.get("tags", [])
        if not isinstance(raw_tags, list) or not all(isinstance(tag, str) for tag in raw_tags):
            raise CorpusError(f"Corpus document {document_id} has invalid tags")
        uri = document.get("uri")
        if uri is not None and (
            not isinstance(uri, str) or urlparse(uri).scheme not in {"https", "http"}
        ):
            raise CorpusError(f"Corpus document {document_id} has an invalid URI")
        chunks.append(
            KnowledgeChunk(
                id=document_id,
                title=document["title"].strip(),
                section=document["section"].strip(),
                content=document["content"].strip(),
                uri=uri,
                tags=tuple(tag.strip() for tag in raw_tags if tag.strip()),
            )
        )
    return chunks


class DemoRetriever:
    """Small-corpus BM25 retriever with deterministic concept expansion."""

    strategy = "bm25+concept-expansion"

    def __init__(self, corpus_path: Path) -> None:
        self.corpus_path = corpus_path
        self.chunks = _load_chunks(corpus_path)
        self._documents = [self._weighted_tokens(chunk) for chunk in self.chunks]
        self._document_frequencies: Counter[str] = Counter()
        for tokens in self._documents:
            self._document_frequencies.update(set(tokens))
        self._average_length = sum(map(len, self._documents)) / len(self._documents)

    @staticmethod
    def _weighted_tokens(chunk: KnowledgeChunk) -> list[str]:
        content = tokenize(chunk.content)
        title = tokenize(chunk.title)
        section = tokenize(chunk.section)
        tags = tokenize(" ".join(chunk.tags))
        return content + title * 3 + section * 2 + tags * 2

    def _bm25(self, document_tokens: list[str], query_tokens: list[str]) -> float:
        counts = Counter(document_tokens)
        document_length = len(document_tokens)
        score = 0.0
        k1 = 1.5
        b = 0.75
        for token in set(query_tokens):
            frequency = counts[token]
            if not frequency:
                continue
            document_frequency = self._document_frequencies[token]
            inverse_document_frequency = math.log(
                1 + (len(self._documents) - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            denominator = frequency + k1 * (1 - b + b * document_length / self._average_length)
            score += inverse_document_frequency * frequency * (k1 + 1) / denominator
        return score

    async def search(self, query: str, top_k: int) -> list[RetrievedChunk]:
        original_tokens = tokenize(query)
        if not original_tokens:
            return []
        expanded_terms = _concept_expansions(query)
        expanded_tokens = [
            token
            for token in tokenize(" ".join(expanded_terms))
            if token not in set(original_tokens)
        ]
        query_lower = " ".join(tokenize(query, remove_stop_words=False))

        raw_results: list[tuple[float, KnowledgeChunk]] = []
        for chunk, document_tokens in zip(self.chunks, self._documents, strict=True):
            raw_score = self._bm25(document_tokens, original_tokens)
            raw_score += self._bm25(document_tokens, expanded_tokens) * 0.25
            searchable_title = " ".join(tokenize(chunk.title, remove_stop_words=False))
            searchable_tags = " ".join(tokenize(" ".join(chunk.tags), remove_stop_words=False))
            if len(query_lower) >= 4 and query_lower in f"{searchable_title} {searchable_tags}":
                raw_score += 3.0
            title_overlap = len(set(original_tokens) & set(tokenize(chunk.title)))
            raw_score += title_overlap * 0.7
            if raw_score > 0:
                raw_results.append((raw_score, chunk))

        raw_results.sort(key=lambda item: (-item[0], item[1].id))
        results: list[RetrievedChunk] = []
        strongest = raw_results[0][0] if raw_results else 0.0
        relevant_results = [
            item
            for item in raw_results
            if item[0] >= max(ABSOLUTE_RELEVANCE_FLOOR, strongest * RELATIVE_RELEVANCE_FLOOR)
        ]
        for raw_score, chunk in relevant_results[:top_k]:
            normalized = min(1.0, 1.0 - math.exp(-raw_score / 7.0))
            results.append(
                RetrievedChunk(
                    chunk=chunk,
                    score=round(normalized, 6),
                    keyword_score=round(normalized, 6),
                    metadata={"raw_bm25": f"{raw_score:.6f}"},
                )
            )
        return results

    async def readiness(self) -> tuple[bool, str]:
        if self.chunks and self.corpus_path.is_file():
            return True, f"{len(self.chunks)} bundled knowledge records loaded"
        return False, "knowledge records are unavailable"


def _best_excerpt(content: str, query: str, limit: int = 500) -> str:
    sentences = [
        sentence.strip() for sentence in SENTENCE_PATTERN.split(content) if sentence.strip()
    ]
    query_tokens = set(tokenize(query))
    ranked = sorted(
        enumerate(sentences),
        key=lambda item: (
            -len(set(tokenize(item[1])) & query_tokens),
            item[0],
        ),
    )
    selected_indices = sorted(item[0] for item in ranked[:2])
    selected = " ".join(sentences[index] for index in selected_indices) if ranked else content
    if len(selected) <= limit:
        return selected
    shortened = selected[: limit - 1].rsplit(" ", 1)[0]
    return f"{shortened}…"


class DemoAnswerGenerator:
    """Generate concise extractive answers whose claims retain source markers."""

    async def generate(
        self,
        *,
        message: str,
        query: str,
        history: list[ChatTurn],
        sources: list[RetrievedChunk],
    ) -> str:
        del message, history
        if not sources:
            return (
                "I could not find enough support for that question in the bundled cloud "
                "knowledge base. Try naming a cloud concept such as autoscaling, IAM, "
                "disaster recovery, containers, networking, or CI/CD."
            )

        lead = "Here is the source-grounded explanation:"
        bullets = [
            f"- **{result.chunk.title}:** {_best_excerpt(result.chunk.content, query)} [{index}]"
            for index, result in enumerate(sources, start=1)
        ]
        follow_up = (
            "\n\nA good next step is to turn the relevant principle into a small design "
            "decision and state the reliability, security, cost, and operational tradeoffs."
        )
        return f"{lead}\n\n" + "\n".join(bullets) + follow_up

    async def readiness(self) -> tuple[bool, str]:
        return True, "deterministic answer generator available"


def chunk_to_public_dict(chunk: KnowledgeChunk) -> dict[str, Any]:
    """Expose corpus content to developer tooling without dataclass internals."""
    return {
        "id": chunk.id,
        "title": chunk.title,
        "section": chunk.section,
        "content": chunk.content,
        "uri": chunk.uri,
        "tags": list(chunk.tags),
    }
