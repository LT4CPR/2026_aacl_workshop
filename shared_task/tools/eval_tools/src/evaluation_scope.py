"""Evaluation section-scope configuration shared by all evaluator paths."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


OFFICIAL_SCORED_SECTION_IDS = tuple(str(section_id) for section_id in range(3, 12))


@dataclass(frozen=True)
class EvaluationScope:
    """Resolved section selection and where it came from."""

    section_ids: tuple[str, ...] | None
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "sections": list(self.section_ids) if self.section_ids is not None else "all",
            "source": self.source,
        }


def _normalize_section_values(value: Any, *, location: str) -> tuple[str, ...] | None:
    """Normalize a selection within the official scored sections (3--11)."""
    if value is None:
        return OFFICIAL_SCORED_SECTION_IDS
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lower() == "all":
            return OFFICIAL_SCORED_SECTION_IDS
        values: Iterable[Any] = stripped.split(",")
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        raise ValueError(
            f"{location} must be 'all', a comma-separated string, or a list of section IDs"
        )

    normalized: list[str] = []
    for item in values:
        if isinstance(item, bool) or not isinstance(item, (str, int)):
            raise ValueError(f"{location} contains an invalid section ID: {item!r}")
        section_id = str(item).strip()
        if not section_id:
            raise ValueError(f"{location} contains an empty section ID")
        if section_id not in normalized:
            normalized.append(section_id)
    if not normalized:
        raise ValueError(f"{location} must contain at least one section ID or 'all'")
    disallowed = [
        section_id
        for section_id in normalized
        if section_id not in OFFICIAL_SCORED_SECTION_IDS
    ]
    if disallowed:
        allowed = ", ".join(OFFICIAL_SCORED_SECTION_IDS)
        rejected = ", ".join(disallowed)
        raise ValueError(
            f"{location} contains non-scored section ID(s): {rejected}; "
            f"the official evaluation scope is {allowed}"
        )
    return tuple(normalized)


def load_configured_scope(config_path: Path) -> EvaluationScope:
    """Load the optional top-level ``evaluation_scope`` block."""
    try:
        yaml = importlib.import_module("yaml")
    except ImportError as exc:
        raise SystemExit(
            "evaluation scope configuration needs PyYAML; install requirements.txt"
        ) from exc
    if not config_path.is_file():
        raise SystemExit(f"evaluation config not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    scope = raw.get("evaluation_scope")
    if scope is None:
        return EvaluationScope(OFFICIAL_SCORED_SECTION_IDS, "default")
    if not isinstance(scope, dict):
        raise ValueError("evaluation_scope must be a mapping")
    section_ids = _normalize_section_values(
        scope.get("sections", "all"),
        location="evaluation_scope.sections",
    )
    return EvaluationScope(section_ids, "config")


def resolve_evaluation_scope(
    config_path: Path,
    cli_sections: str | None = None,
) -> EvaluationScope:
    """Resolve CLI-over-config section selection."""
    if cli_sections is None:
        return load_configured_scope(config_path)
    return EvaluationScope(
        _normalize_section_values(cli_sections, location="--sections"),
        "cli",
    )
