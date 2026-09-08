"""Normalize subsection-correspondence configuration and matching keys."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


SUBSECTION_ALIGNMENT_METHODS = (
    "id_only",
    "header_only",
    "both_id_and_header",
)
DEFAULT_SUBSECTION_ALIGNMENT_METHOD = "header_only"
_WHITESPACE_RE = re.compile(r"\s+")
_BOTH_SEPARATOR = "\x1f"


def normalize_subsection_header(value: Any) -> str:
    """Return a stable exact-match key without imposing a header inventory."""
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", str(value))
    return _WHITESPACE_RE.sub(" ", normalized).strip().casefold()


def normalize_subsection_alignment_method(value: Any) -> str:
    """Validate and canonicalize a configured alignment method."""
    method = str(value).strip().lower().replace("-", "_")
    if method not in SUBSECTION_ALIGNMENT_METHODS:
        choices = ", ".join(SUBSECTION_ALIGNMENT_METHODS)
        raise ValueError(
            f"subsection_alignment_method must be one of {choices}; got {value!r}"
        )
    return method


def resolve_subsection_alignment_method(config: dict[str, Any]) -> str:
    """Resolve the global method, defaulting to header-only correspondence."""
    return normalize_subsection_alignment_method(
        config.get(
            "subsection_alignment_method",
            DEFAULT_SUBSECTION_ALIGNMENT_METHOD,
        )
    )


def subsection_alignment_key(
    subsection_id: Any,
    subsection_header: Any,
    method: str,
) -> str:
    """Build a dynamic key from fields present in an input subsection."""
    normalized_method = normalize_subsection_alignment_method(method)
    normalized_id = str(subsection_id or "").strip()
    normalized_header = normalize_subsection_header(subsection_header)

    if normalized_method in {"id_only", "both_id_and_header"} and not normalized_id:
        raise ValueError(
            f"subsection id is required for {normalized_method} alignment"
        )
    if normalized_method in {"header_only", "both_id_and_header"} and not normalized_header:
        raise ValueError(
            f"subsection header is required for {normalized_method} alignment"
        )

    if normalized_method == "id_only":
        return normalized_id
    if normalized_method == "header_only":
        return normalized_header
    return f"{normalized_id}{_BOTH_SEPARATOR}{normalized_header}"


def display_subsection_alignment_key(key: str, method: str) -> str:
    """Render an internal key in readable diagnostics."""
    normalized_method = normalize_subsection_alignment_method(method)
    if normalized_method == "id_only":
        return key
    if normalized_method == "header_only":
        return f"header={key}"
    subsection_id, _, header = key.partition(_BOTH_SEPARATOR)
    return f"id={subsection_id}|header={header}"
