"""Prometheus instrumentation with an isolated registry per application."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram


class ServiceMetrics:
    """Metrics used by HTTP middleware and the RAG endpoint."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        self.http_requests = Counter(
            "cloud_tutor_http_requests_total",
            "HTTP requests handled by the service.",
            ("method", "route", "status"),
            registry=self.registry,
        )
        self.http_duration = Histogram(
            "cloud_tutor_http_request_duration_seconds",
            "End-to-end HTTP request duration.",
            ("method", "route"),
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
            registry=self.registry,
        )
        self.chat_requests = Counter(
            "cloud_tutor_chat_requests_total",
            "Grounded chat attempts.",
            ("mode", "outcome"),
            registry=self.registry,
        )
        self.retrieval_confidence = Histogram(
            "cloud_tutor_retrieval_confidence",
            "Normalized confidence of RAG retrieval.",
            ("mode",),
            buckets=(0.0, 0.1, 0.25, 0.5, 0.7, 0.85, 0.95, 1.0),
            registry=self.registry,
        )
