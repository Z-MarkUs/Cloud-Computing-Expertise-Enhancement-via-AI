"""Build provider combinations from typed settings."""

from __future__ import annotations

from cloud_tutor.config import Settings
from cloud_tutor.providers.demo import DemoAnswerGenerator, DemoRetriever
from cloud_tutor.service import RagService


def build_service(settings: Settings) -> RagService:
    """Create the configured RAG service without importing unused cloud SDKs."""
    if settings.mode == "demo":
        return RagService(
            settings=settings,
            retriever=DemoRetriever(settings.resolved_knowledge_path()),
            generator=DemoAnswerGenerator(),
        )

    from cloud_tutor.providers.azure import AzureOpenAIAnswerGenerator, AzureSearchRetriever

    return RagService(
        settings=settings,
        retriever=AzureSearchRetriever(settings),
        generator=AzureOpenAIAnswerGenerator(settings),
    )
