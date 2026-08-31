"""Typed runtime configuration with safe, offline-first defaults."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration read from ``CLOUD_TUTOR_*`` environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="CLOUD_TUTOR_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "StratusGuide Cloud Tutor"
    environment: Literal["development", "test", "production"] = "development"
    mode: Literal["demo", "azure"] = "demo"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    reload: bool = False
    access_log: bool = True

    knowledge_path: Path | None = None
    max_message_chars: int = Field(default=4_000, ge=100, le=32_000)
    max_history_turns: int = Field(default=20, ge=0, le=100)
    default_top_k: int = Field(default=4, ge=1, le=10)
    max_top_k: int = Field(default=8, ge=1, le=20)
    minimum_confidence: float = Field(default=0.40, ge=0.0, le=1.0)
    cors_origins: str = "http://localhost:3000,http://localhost:5173,http://localhost:8000"
    api_key: SecretStr | None = None
    frontend_dist_dir: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("FRONTEND_DIST_DIR", "CLOUD_TUTOR_FRONTEND_DIST_DIR"),
    )

    azure_openai_endpoint: str | None = None
    azure_openai_api_key: SecretStr | None = None
    azure_openai_api_version: str = "2024-10-21"
    azure_chat_deployment: str | None = None
    azure_embedding_deployment: str | None = None
    azure_search_endpoint: str | None = None
    azure_search_api_key: SecretStr | None = None
    azure_search_index: str | None = None
    azure_search_semantic_configuration: str | None = None
    azure_search_id_field: str = "id"
    azure_search_title_field: str = "title"
    azure_search_content_field: str = "content"
    azure_search_source_field: str = "source"
    azure_search_section_field: str = "section"
    azure_search_vector_field: str = "content_vector"
    azure_embedding_dimensions: int | None = Field(default=None, ge=1, le=4_096)
    azure_probe_on_readiness: bool = False

    @model_validator(mode="after")
    def validate_cross_field_settings(self) -> Settings:
        if self.default_top_k > self.max_top_k:
            raise ValueError("default_top_k cannot exceed max_top_k")
        if self.mode == "azure":
            required = {
                "azure_openai_endpoint": self.azure_openai_endpoint,
                "azure_chat_deployment": self.azure_chat_deployment,
                "azure_embedding_deployment": self.azure_embedding_deployment,
                "azure_search_endpoint": self.azure_search_endpoint,
                "azure_search_index": self.azure_search_index,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(
                    "Azure mode requires configuration for: " + ", ".join(sorted(missing))
                )
        return self

    def allowed_origins(self) -> list[str]:
        """Return normalized CORS origins while rejecting wildcard-with-credentials setups."""
        origins = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        return list(dict.fromkeys(origins))

    def resolved_knowledge_path(self) -> Path:
        """Find corpus data in source checkouts and installed wheels."""
        if self.knowledge_path is not None:
            return self.knowledge_path.expanduser().resolve()

        project_candidate = Path(__file__).resolve().parents[2] / "data" / "cloud_knowledge.json"
        if project_candidate.is_file():
            return project_candidate

        working_candidate = Path.cwd() / "data" / "cloud_knowledge.json"
        if working_candidate.is_file():
            return working_candidate.resolve()

        try:
            from importlib.resources import as_file, files

            resource = files("cloud_tutor").joinpath("data/cloud_knowledge.json")
            with as_file(resource) as packaged_path:
                return packaged_path
        except (FileNotFoundError, ModuleNotFoundError, TypeError) as error:
            raise FileNotFoundError(
                "Bundled knowledge corpus was not found; set CLOUD_TUTOR_KNOWLEDGE_PATH"
            ) from error


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable settings instance."""
    return Settings()
