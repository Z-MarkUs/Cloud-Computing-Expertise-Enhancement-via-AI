"""Provider protocols keep orchestration independent of cloud SDKs."""

from __future__ import annotations

from typing import Protocol

from cloud_tutor.models import ChatTurn, RetrievedChunk


class Retriever(Protocol):
    """Search a knowledge source and return consistently scored passages."""

    strategy: str

    async def search(self, query: str, top_k: int) -> list[RetrievedChunk]: ...

    async def readiness(self) -> tuple[bool, str]: ...


class AnswerGenerator(Protocol):
    """Generate an answer that is grounded in retrieved passages."""

    async def generate(
        self,
        *,
        message: str,
        query: str,
        history: list[ChatTurn],
        sources: list[RetrievedChunk],
    ) -> str: ...

    async def readiness(self) -> tuple[bool, str]: ...
