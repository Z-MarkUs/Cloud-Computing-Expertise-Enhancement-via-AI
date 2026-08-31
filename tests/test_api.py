"""Integration tests for public API and operational contracts."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cloud_tutor.app import create_app
from cloud_tutor.config import Settings
from cloud_tutor.errors import ProviderUnavailableError


def test_public_config_contains_capabilities_but_no_secrets(client: TestClient) -> None:
    response = client.get("/api/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "demo"
    assert payload["authentication_required"] is False
    assert "citations" in payload["features"]
    assert "api_key" not in response.text


@pytest.mark.parametrize("path", ["/healthz", "/health/live"])
def test_liveness_routes_are_stable(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "mode": "demo",
        "version": "2.0.0",
        "checks": {"process": "running"},
    }


def test_demo_readiness_proves_corpus_and_generator_loaded(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert "bundled knowledge records loaded" in payload["checks"]["retriever"]
    assert payload["checks"]["generator"] == "deterministic answer generator available"


def test_chat_returns_stable_grounded_contract(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={"message": "How do RPO and RTO differ?", "top_k": 3},
        headers={"X-Request-ID": "contract-test-1"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "contract-test-1"
    payload = response.json()
    assert set(payload) == {"answer", "citations", "trace"}
    assert payload["citations"]
    assert set(payload["citations"][0]) == {
        "id",
        "title",
        "section",
        "excerpt",
        "score",
        "uri",
    }
    assert payload["citations"][0]["title"] == "RPO, RTO, backup, and disaster recovery"
    assert "[1]" in payload["answer"]
    assert payload["trace"]["request_id"] == "contract-test-1"
    assert payload["trace"]["mode"] == "demo"
    assert payload["trace"]["retrieval_strategy"] == "bm25+concept-expansion"
    assert payload["trace"]["retrieved_documents"][0]["id"] == "rpo-rto-backup"
    assert 0 <= payload["trace"]["confidence"] <= 1
    assert payload["trace"]["total_ms"] >= payload["trace"]["retrieval_ms"]


def test_demo_response_is_deterministic_except_observability_fields(client: TestClient) -> None:
    first = client.post("/api/chat", json={"message": "Explain object storage"}).json()
    second = client.post("/api/chat", json={"message": "Explain object storage"}).json()

    assert first["answer"] == second["answer"]
    assert first["citations"] == second["citations"]
    assert first["trace"]["query"] == second["trace"]["query"]
    assert first["trace"]["retrieved_documents"] == second["trace"]["retrieved_documents"]


def test_multi_turn_follow_up_is_resolved_into_retrieval_query(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={
            "message": "What about its security responsibilities?",
            "history": [
                {"role": "user", "content": "Explain the difference between IaaS and PaaS."},
                {"role": "assistant", "content": "IaaS leaves more operations to the customer."},
            ],
        },
    )

    assert response.status_code == 200
    query = response.json()["trace"]["query"]
    assert "Explain the difference between IaaS and PaaS" in query
    assert "Follow-up: What about its security responsibilities?" in query


def test_unknown_question_abstains_without_fake_citations(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={"message": "Who won the lunar chess championship on Europa in 1842?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["citations"] == []
    assert "could not find enough support" in payload["answer"]
    assert payload["trace"]["confidence"] == 0


def test_availability_zone_answer_excludes_weak_migration_tail(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={"message": "How do availability zones improve resilience?", "top_k": 4},
    )

    assert response.status_code == 200
    payload = response.json()
    retrieved_ids = [item["id"] for item in payload["trace"]["retrieved_documents"]]
    citation_titles = [citation["title"] for citation in payload["citations"]]
    assert retrieved_ids == ["regions-availability-zones"]
    assert citation_titles == ["Regions, availability zones, and failure domains"]
    assert "cloud-migration" not in retrieved_ids
    assert all("migration" not in title.casefold() for title in citation_titles)


@pytest.mark.parametrize(
    ("payload", "status", "field"),
    [
        ({}, 422, "message"),
        ({"message": "   "}, 422, "message"),
        ({"message": "valid", "top_k": 0}, 422, "top_k"),
        ({"message": "valid", "unknown": True}, 422, "unknown"),
        (
            {
                "message": "valid",
                "history": [
                    {"role": "user", "content": "one"},
                    {"role": "user", "content": "two"},
                ],
            },
            422,
            "history",
        ),
    ],
)
def test_invalid_requests_use_safe_error_contract(
    client: TestClient,
    payload: dict[str, object],
    status: int,
    field: str,
) -> None:
    response = client.post("/api/chat", json=payload)

    assert response.status_code == status
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["request_id"]
    assert any(item["field"] == field for item in body["error"].get("details") or [])


def test_runtime_limits_are_enforced(settings: Settings) -> None:
    limited = settings.model_copy(
        update={"max_message_chars": 10, "max_history_turns": 1, "max_top_k": 2}
    )
    with TestClient(create_app(limited)) as client:
        too_large = client.post("/api/chat", json={"message": "x" * 11})
        too_much_history = client.post(
            "/api/chat",
            json={
                "message": "okay",
                "history": [
                    {"role": "user", "content": "a"},
                    {"role": "assistant", "content": "b"},
                ],
            },
        )
        too_many_sources = client.post("/api/chat", json={"message": "okay", "top_k": 3})

    assert too_large.status_code == 413
    assert too_large.json()["error"]["code"] == "request_too_large"
    assert too_much_history.status_code == 422
    assert too_many_sources.status_code == 422


def test_optional_api_key_protects_only_chat(settings: Settings) -> None:
    protected = settings.model_copy(update={"api_key": "correct-horse"})
    with TestClient(create_app(protected)) as client:
        live = client.get("/healthz")
        denied = client.post("/api/chat", json={"message": "Explain IaaS"})
        allowed = client.post(
            "/api/chat",
            json={"message": "Explain IaaS"},
            headers={"X-API-Key": "correct-horse"},
        )

    assert live.status_code == 200
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "authentication_required"
    assert denied.headers["WWW-Authenticate"] == "ApiKey"
    assert allowed.status_code == 200


def test_invalid_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/healthz", headers={"X-Request-ID": "bad id with spaces"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "bad id with spaces"


def test_cors_allows_configured_origin(client: TestClient) -> None:
    response = client.options(
        "/api/chat",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_metrics_include_http_and_chat_signals(client: TestClient) -> None:
    assert client.post("/api/chat", json={"message": "Explain autoscaling"}).status_code == 200
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "cloud_tutor_http_requests_total" in response.text
    assert "cloud_tutor_chat_requests_total" in response.text
    assert 'mode="demo",outcome="success"' in response.text
    assert "cloud_tutor_retrieval_confidence" in response.text


class _FailingService:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def chat(self, *_args: object, **_kwargs: object) -> None:
        raise self.error

    async def readiness(self) -> tuple[bool, dict[str, str]]:
        return False, {"provider": "failed"}


@pytest.fixture
def failing_client(settings: Settings) -> Iterator[TestClient]:
    service = _FailingService(ProviderUnavailableError("private SDK detail"))
    with TestClient(
        create_app(settings, service=service),
        raise_server_exceptions=False,
    ) as test_client:
        yield test_client


def test_provider_failure_is_safe_and_readiness_fails(failing_client: TestClient) -> None:
    response = failing_client.post("/api/chat", json={"message": "Explain IaaS"})
    ready = failing_client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"
    assert "private SDK detail" not in response.text
    assert ready.status_code == 503
    assert ready.json()["status"] == "not_ready"


def test_unexpected_failure_does_not_leak_exception(settings: Settings) -> None:
    service = _FailingService(RuntimeError("database password was hunter2"))
    with TestClient(
        create_app(settings, service=service),
        raise_server_exceptions=False,
    ) as client:
        response = client.post("/api/chat", json={"message": "Explain IaaS"})

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "hunter2" not in response.text


def test_legacy_flask_endpoint_is_not_exposed(client: TestClient) -> None:
    response = client.post("/api/ask", json={"prompt": "test"})

    assert response.status_code == 404


def test_production_spa_fallback_preserves_asset_404s_and_security_headers(
    settings: Settings,
    tmp_path: Path,
) -> None:
    (tmp_path / "index.html").write_text(
        "<!doctype html><title>StratusGuide</title>",
        encoding="utf-8",
    )
    production = settings.model_copy(
        update={"environment": "production", "frontend_dist_dir": tmp_path}
    )

    with TestClient(create_app(production)) as client:
        deep_link = client.get("/showcase/deep-link")
        missing_asset = client.get("/assets/missing.js")

    assert deep_link.status_code == 200
    assert "StratusGuide" in deep_link.text
    assert deep_link.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in deep_link.headers["content-security-policy"]
    assert missing_asset.status_code == 404
