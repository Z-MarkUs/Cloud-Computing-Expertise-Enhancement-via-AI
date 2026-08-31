"""Offline contract tests for the optional Azure adapters.

SDK modules are represented by small fakes so the default development and CI
install remains credential-free and does not require the ``azure`` extra.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from cloud_tutor.config import Settings
from cloud_tutor.errors import ProviderUnavailableError
from cloud_tutor.models import ChatTurn, KnowledgeChunk, RetrievedChunk
from cloud_tutor.providers.azure import AzureOpenAIAnswerGenerator, AzureSearchRetriever


@dataclass
class _FakeState:
    search_results: list[dict[str, Any]] = field(default_factory=list)
    search_error: Exception | None = None
    embedding_error: Exception | None = None
    chat_error: Exception | None = None
    chat_content: str | None = "A grounded Azure answer [1]."
    search_kwargs: dict[str, Any] = field(default_factory=dict)
    embedding_kwargs: dict[str, Any] = field(default_factory=dict)
    chat_kwargs: dict[str, Any] = field(default_factory=dict)
    clients: list[Any] = field(default_factory=list)
    token_provider_calls: int = 0
    search_closed: bool = False
    openai_close_count: int = 0


def _install_fake_sdks(monkeypatch: pytest.MonkeyPatch, state: _FakeState) -> None:
    azure = ModuleType("azure")
    azure_core = ModuleType("azure.core")
    azure_credentials = ModuleType("azure.core.credentials")
    azure_identity = ModuleType("azure.identity")
    azure_search = ModuleType("azure.search")
    azure_documents = ModuleType("azure.search.documents")
    azure_models = ModuleType("azure.search.documents.models")
    openai = ModuleType("openai")

    class AzureKeyCredential:
        def __init__(self, key: str) -> None:
            self.key = key

    class DefaultAzureCredential:
        pass

    def get_bearer_token_provider(*_args: object) -> object:
        state.token_provider_calls += 1
        return object()

    class VectorizedQuery:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class SearchClient:
        def __init__(self, **kwargs: Any) -> None:
            self.init_kwargs = kwargs

        def search(self, **kwargs: Any) -> list[dict[str, Any]]:
            state.search_kwargs = kwargs
            if state.search_error:
                raise state.search_error
            return state.search_results

        def get_document_count(self) -> int:
            if state.search_error:
                raise state.search_error
            return len(state.search_results)

        def close(self) -> None:
            state.search_closed = True

    class AsyncAzureOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            self.init_kwargs = kwargs
            self.embeddings = SimpleNamespace(create=self.create_embedding)
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create_chat_completion)
            )
            state.clients.append(self)

        async def create_embedding(self, **kwargs: Any) -> Any:
            state.embedding_kwargs = kwargs
            if state.embedding_error:
                raise state.embedding_error
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])])

        async def create_chat_completion(self, **kwargs: Any) -> Any:
            state.chat_kwargs = kwargs
            if state.chat_error:
                raise state.chat_error
            message = SimpleNamespace(content=state.chat_content)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        async def close(self) -> None:
            state.openai_close_count += 1

    azure_credentials.AzureKeyCredential = AzureKeyCredential  # type: ignore[attr-defined]
    azure_identity.DefaultAzureCredential = DefaultAzureCredential  # type: ignore[attr-defined]
    azure_identity.get_bearer_token_provider = get_bearer_token_provider  # type: ignore[attr-defined]
    azure_documents.SearchClient = SearchClient  # type: ignore[attr-defined]
    azure_models.VectorizedQuery = VectorizedQuery  # type: ignore[attr-defined]
    openai.AsyncAzureOpenAI = AsyncAzureOpenAI  # type: ignore[attr-defined]

    modules = {
        "azure": azure,
        "azure.core": azure_core,
        "azure.core.credentials": azure_credentials,
        "azure.identity": azure_identity,
        "azure.search": azure_search,
        "azure.search.documents": azure_documents,
        "azure.search.documents.models": azure_models,
        "openai": openai,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


def _azure_settings(**updates: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "mode": "azure",
        "environment": "test",
        "azure_openai_endpoint": "https://openai.example",
        "azure_openai_api_key": "openai-key",
        "azure_chat_deployment": "chat-deployment",
        "azure_embedding_deployment": "embedding-deployment",
        "azure_search_endpoint": "https://search.example",
        "azure_search_api_key": "search-key",
        "azure_search_index": "knowledge",
        "azure_search_semantic_configuration": "semantic-default",
        "azure_embedding_dimensions": 3,
    }
    values.update(updates)
    return Settings(**values)


@pytest.fixture
def azure_result() -> dict[str, Any]:
    return {
        "id": "azure-doc-1",
        "title": "Azure reliability",
        "section": "Zones",
        "content": "Availability zones isolate independent datacenter failures.",
        "source": "https://example.com/reliability",
        "@search.score": 2.0,
        "@search.reranker_score": 3.2,
    }


def test_azure_search_maps_hybrid_result_and_semantic_options(
    monkeypatch: pytest.MonkeyPatch, azure_result: dict[str, Any]
) -> None:
    state = _FakeState(search_results=[azure_result, {"id": "empty"}])
    _install_fake_sdks(monkeypatch, state)
    retriever = AzureSearchRetriever(_azure_settings())

    results = asyncio.run(retriever.search("availability zones", 3))

    assert len(results) == 1
    assert results[0].chunk.id == "azure-doc-1"
    assert results[0].score == 0.8
    assert results[0].vector_score is not None
    assert state.embedding_kwargs == {
        "model": "embedding-deployment",
        "input": ["availability zones"],
        "dimensions": 3,
    }
    assert state.search_kwargs["query_type"] == "semantic"
    assert state.search_kwargs["semantic_configuration_name"] == "semantic-default"
    assert state.search_kwargs["top"] == 3


def test_azure_search_without_semantic_ranker_uses_normalized_search_score(
    monkeypatch: pytest.MonkeyPatch, azure_result: dict[str, Any]
) -> None:
    azure_result.pop("@search.reranker_score")
    state = _FakeState(search_results=[azure_result])
    _install_fake_sdks(monkeypatch, state)
    retriever = AzureSearchRetriever(
        _azure_settings(
            azure_search_semantic_configuration=None,
            azure_embedding_dimensions=None,
        )
    )

    results = asyncio.run(retriever.search("zones", 1))

    assert results[0].score == results[0].vector_score
    assert "query_type" not in state.search_kwargs
    assert "dimensions" not in state.embedding_kwargs


def test_azure_search_wraps_dependency_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _FakeState(embedding_error=RuntimeError("private credential detail"))
    _install_fake_sdks(monkeypatch, state)
    retriever = AzureSearchRetriever(_azure_settings())

    with pytest.raises(ProviderUnavailableError, match="Azure retrieval failed"):
        asyncio.run(retriever.search("zones", 1))


def test_azure_readiness_supports_config_only_and_live_probe(
    monkeypatch: pytest.MonkeyPatch, azure_result: dict[str, Any]
) -> None:
    state = _FakeState(search_results=[azure_result])
    _install_fake_sdks(monkeypatch, state)
    config_only = AzureSearchRetriever(_azure_settings(azure_probe_on_readiness=False))
    live_probe = AzureSearchRetriever(_azure_settings(azure_probe_on_readiness=True))

    assert asyncio.run(config_only.readiness()) == (
        True,
        "Azure clients configured; live dependency probe disabled",
    )
    assert asyncio.run(live_probe.readiness()) == (
        True,
        "Azure AI Search reachable with 1 indexed records",
    )
    state.search_error = RuntimeError("offline")
    assert asyncio.run(live_probe.readiness()) == (False, "Azure AI Search probe failed")


def test_azure_managed_identity_auth_and_resource_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _FakeState()
    _install_fake_sdks(monkeypatch, state)
    settings = _azure_settings(
        azure_openai_api_key=None,
        azure_search_api_key=None,
    )
    retriever = AzureSearchRetriever(settings)
    generator = AzureOpenAIAnswerGenerator(settings)

    asyncio.run(retriever.aclose())
    asyncio.run(generator.aclose())

    assert state.token_provider_calls == 2
    assert state.search_closed is True
    assert state.openai_close_count == 2


def test_azure_generator_supplies_grounded_sources_and_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _FakeState(chat_content="Use independent zones [1].")
    _install_fake_sdks(monkeypatch, state)
    generator = AzureOpenAIAnswerGenerator(_azure_settings())
    source = RetrievedChunk(
        chunk=KnowledgeChunk(
            id="one",
            title="Availability zones",
            section="Reliability",
            content="Zones use independent power and networking.",
            uri="https://example.com",
        ),
        score=0.9,
    )

    answer = asyncio.run(
        generator.generate(
            message="How do zones help?",
            query="zones",
            history=[ChatTurn(role="user", content="Explain regions")],
            sources=[source],
        )
    )

    assert answer == "Use independent zones [1]."
    assert state.chat_kwargs["model"] == "chat-deployment"
    messages = state.chat_kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "Explain regions"}
    assert "SOURCE [1]" in messages[-1]["content"]
    assert "Availability zones" in messages[-1]["content"]
    assert asyncio.run(generator.readiness()) == (True, "Azure OpenAI client configured")


def test_azure_generator_abstains_without_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _FakeState()
    _install_fake_sdks(monkeypatch, state)
    generator = AzureOpenAIAnswerGenerator(_azure_settings())

    answer = asyncio.run(
        generator.generate(message="Unknown?", query="unknown", history=[], sources=[])
    )

    assert "could not find enough support" in answer
    assert state.chat_kwargs == {}


@pytest.mark.parametrize(
    ("chat_content", "chat_error"),
    [(None, None), ("unused", RuntimeError("provider detail"))],
)
def test_azure_generator_wraps_empty_and_failed_responses(
    monkeypatch: pytest.MonkeyPatch,
    chat_content: str | None,
    chat_error: Exception | None,
) -> None:
    state = _FakeState(chat_content=chat_content, chat_error=chat_error)
    _install_fake_sdks(monkeypatch, state)
    generator = AzureOpenAIAnswerGenerator(_azure_settings())
    source = RetrievedChunk(
        chunk=KnowledgeChunk("id", "Title", "Section", "Supported text.", None),
        score=1.0,
    )

    with pytest.raises(ProviderUnavailableError):
        asyncio.run(
            generator.generate(
                message="Question",
                query="question",
                history=[],
                sources=[source],
            )
        )
