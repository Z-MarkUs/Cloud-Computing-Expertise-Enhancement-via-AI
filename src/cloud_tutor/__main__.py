"""Command-line entry point for the Cloud Tutor API."""

from __future__ import annotations

import uvicorn

from cloud_tutor.config import Settings


def main() -> None:
    """Run the API with Uvicorn using environment-backed settings."""
    settings = Settings()
    uvicorn.run(
        "cloud_tutor.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        access_log=settings.access_log,
    )


if __name__ == "__main__":  # pragma: no cover - exercised through the console script
    main()
