# Contributing to StratusGuide

Thanks for improving transparent cloud education. Keep changes small enough to review and add
evidence for behavior that changes.

## Local setup

1. Install Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 22+, and pnpm.
2. Run `uv sync --locked --all-extras --dev` from the repository root.
3. Run `pnpm install --frozen-lockfile` inside `frontend/`.
4. Copy `.env.example` to `.env` only when testing non-default configuration.

## Quality gate

Before opening a pull request, run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
uv run python -m evals.run_evaluation
pnpm --dir frontend lint
pnpm --dir frontend test
pnpm --dir frontend build
```

New retrieval behavior should include an evaluation case, not only a unit test. Do not raise a
reported metric by weakening the evaluation set or changing expected evidence without explaining
the reason in the pull request.

## Pull requests

- Explain the problem and the observable result.
- Link tests, evaluation output, screenshots, or traces that verify the change.
- Call out security, cost, privacy, accessibility, and migration implications.
- Never include live credentials or proprietary source documents.
