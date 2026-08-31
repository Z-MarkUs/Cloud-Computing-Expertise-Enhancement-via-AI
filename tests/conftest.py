"""Shared fixtures for isolated, credential-free backend tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cloud_tutor.app import create_app
from cloud_tutor.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = PROJECT_ROOT / "data" / "cloud_knowledge.json"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        mode="demo",
        environment="test",
        knowledge_path=CORPUS_PATH,
        cors_origins="http://localhost:5173",
        api_key=None,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
