"""Tests for secure and portable settings behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from cloud_tutor.config import Settings
from cloud_tutor.errors import ProviderConfigurationError
from cloud_tutor.providers.factory import build_service


def test_demo_mode_is_default_and_resolves_bundled_corpus() -> None:
    settings = Settings(_env_file=None, mode="demo")

    assert settings.mode == "demo"
    assert settings.resolved_knowledge_path().name == "cloud_knowledge.json"
    assert settings.resolved_knowledge_path().is_file()


def test_settings_reject_invalid_top_k_relationship() -> None:
    with pytest.raises(ValidationError, match="default_top_k cannot exceed max_top_k"):
        Settings(_env_file=None, default_top_k=5, max_top_k=4)


def test_azure_mode_lists_missing_configuration_without_values() -> None:
    with pytest.raises(ValidationError) as captured:
        Settings(_env_file=None, mode="azure")

    message = str(captured.value)
    assert "azure_openai_endpoint" in message
    assert "azure_search_index" in message


def test_secret_values_are_masked_in_settings_repr() -> None:
    settings = Settings(_env_file=None, api_key="super-secret-value")

    assert "super-secret-value" not in repr(settings)
    assert "**********" in repr(settings)


def test_cors_origins_are_trimmed_and_deduplicated() -> None:
    settings = Settings(
        _env_file=None,
        cors_origins=" https://one.example,https://two.example,https://one.example ",
    )

    assert settings.allowed_origins() == ["https://one.example", "https://two.example"]


def test_frontend_dist_dir_accepts_unprefixed_container_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FRONTEND_DIST_DIR", str(tmp_path))

    settings = Settings(_env_file=None)

    assert settings.frontend_dist_dir == tmp_path


def test_frontend_dist_dir_accepts_python_field_name(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, frontend_dist_dir=tmp_path)

    assert settings.frontend_dist_dir == tmp_path


def test_missing_optional_azure_sdk_returns_actionable_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        mode="azure",
        azure_openai_endpoint="https://openai.example",
        azure_chat_deployment="chat",
        azure_embedding_deployment="embedding",
        azure_search_endpoint="https://search.example",
        azure_search_index="knowledge",
    )

    real_import = __import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("azure") or name == "openai":
            raise ImportError("optional dependency intentionally hidden")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", blocked_import)
    with pytest.raises(ProviderConfigurationError, match=r"azure.*extra"):
        build_service(settings)
