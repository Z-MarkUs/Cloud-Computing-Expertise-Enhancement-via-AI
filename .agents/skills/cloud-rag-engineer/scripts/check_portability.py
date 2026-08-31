#!/usr/bin/env python3
"""Validate the shared project skill and its two discovery copies."""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

SKILL_NAME = "cloud-rag-engineer"
DISCOVERY_PATHS = (
    Path(".agents/skills") / SKILL_NAME,
    Path(".claude/skills") / SKILL_NAME,
)
IGNORED_PARTS = {"__pycache__"}


def find_repo_root(start: Path) -> Path:
    """Return the nearest ancestor containing the Git administrative entry."""
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    raise ValueError(f"could not locate repository root from {start}")


def skill_files(directory: Path) -> dict[str, Path]:
    """Return portable skill files keyed by POSIX-style relative path."""
    return {
        path.relative_to(directory).as_posix(): path
        for path in directory.rglob("*")
        if path.is_file() and not IGNORED_PARTS.intersection(path.parts) and path.suffix != ".pyc"
    }


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frontmatter_fields(skill_md: Path) -> tuple[dict[str, str], str]:
    """Parse the simple, portable top-level frontmatter used by this skill."""
    content = skill_md.read_text(encoding="utf-8")
    match = re.match(r"\A---\r?\n(?P<header>.*?)\r?\n---(?:\r?\n|\Z)", content, re.DOTALL)
    if match is None:
        raise ValueError(f"{skill_md}: missing YAML frontmatter")

    fields: dict[str, str] = {}
    for line in match.group("header").splitlines():
        if not line or line[0].isspace():
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError(f"{skill_md}: malformed frontmatter line {line!r}")
        fields[key.strip()] = value.strip().strip("\"'")
    return fields, content[match.end() :]


def validate(repo_root: Path) -> list[str]:
    errors: list[str] = []
    resolved = [repo_root / relative for relative in DISCOVERY_PATHS]

    for directory in resolved:
        if not (directory / "SKILL.md").is_file():
            errors.append(f"missing discovery entrypoint: {directory / 'SKILL.md'}")

    if errors:
        return errors

    left_files = skill_files(resolved[0])
    right_files = skill_files(resolved[1])
    if left_files.keys() != right_files.keys():
        missing_left = sorted(right_files.keys() - left_files.keys())
        missing_right = sorted(left_files.keys() - right_files.keys())
        errors.append(
            "skill file sets differ; "
            f"missing from {DISCOVERY_PATHS[0]}={missing_left}, "
            f"missing from {DISCOVERY_PATHS[1]}={missing_right}"
        )
    else:
        for relative in sorted(left_files):
            if digest(left_files[relative]) != digest(right_files[relative]):
                errors.append(f"skill copies differ: {relative}")

    try:
        fields, body = frontmatter_fields(resolved[0] / "SKILL.md")
    except ValueError as error:
        errors.append(str(error))
    else:
        if set(fields) != {"name", "description"}:
            errors.append(
                "shared SKILL.md frontmatter must contain only portable name and description fields"
            )
        if fields.get("name") != SKILL_NAME:
            errors.append(f"skill name must be {SKILL_NAME!r}")
        if not fields.get("description"):
            errors.append("skill description must be non-empty for implicit discovery")
        if not body.strip():
            errors.append("skill instructions must be non-empty")

    agents_md = repo_root / "AGENTS.md"
    claude_md = repo_root / "CLAUDE.md"
    if not agents_md.is_file():
        errors.append("AGENTS.md is missing")
    elif SKILL_NAME not in agents_md.read_text(encoding="utf-8"):
        errors.append(f"AGENTS.md does not route relevant work to {SKILL_NAME}")
    if not claude_md.is_file():
        errors.append("CLAUDE.md is missing")
    else:
        imports = {
            line.strip()
            for line in claude_md.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("@")
        }
        if "@AGENTS.md" not in imports:
            errors.append("CLAUDE.md must import @AGENTS.md to avoid guidance drift")

    reference = resolved[0] / "references/rag-quality.md"
    if not reference.is_file() or not reference.read_text(encoding="utf-8").strip():
        errors.append("referenced RAG quality gates are missing or empty")

    return errors


def main() -> int:
    requested_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
    repo_root = requested_root or find_repo_root(Path(__file__).resolve())
    errors = validate(repo_root)
    if errors:
        print("Project skill portability validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(
        f"Validated {SKILL_NAME}: identical Codex/Claude copies, portable frontmatter, "
        "and shared repository guidance."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
