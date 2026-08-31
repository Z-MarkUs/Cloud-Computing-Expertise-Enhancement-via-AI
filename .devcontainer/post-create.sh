#!/usr/bin/env bash
set -euo pipefail

uv sync --locked --all-extras --dev
pnpm --dir frontend install --frozen-lockfile
uvx pre-commit install --install-hooks

echo "Cloud Tutor development environment is ready."
echo "API: uv run cloud-tutor"
echo "Frontend: pnpm --dir frontend dev"
