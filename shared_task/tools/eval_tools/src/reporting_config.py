"""Reporting-level evaluation configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_AGGREGATION = {
    "within_document": "micro",
    "across_documents": "macro",
}
DEFAULT_PRIMARY_SCORE = {
    "enabled": True,
    "method": "mean_bertscore_f1_bleurt",
}
SUPPORTED_PRIMARY_SCORE_METHODS = {"mean_bertscore_f1_bleurt"}


def load_reporting_config(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    reporting = raw.get("reporting") or {}
    configured = reporting.get("aggregation") or {}
    within = str(
        configured.get("within_document", DEFAULT_AGGREGATION["within_document"])
    ).lower()
    across = str(
        configured.get("across_documents", DEFAULT_AGGREGATION["across_documents"])
    ).lower()
    if within not in {"micro", "macro"}:
        raise ValueError(
            "reporting.aggregation.within_document must be micro or macro"
        )
    if across != "macro":
        raise ValueError(
            "reporting.aggregation.across_documents currently supports only macro; "
            "cross-document micro requires pooled raw metric statistics"
        )
    configured_primary = reporting.get("primary_score") or {}
    enabled = configured_primary.get("enabled", DEFAULT_PRIMARY_SCORE["enabled"])
    if not isinstance(enabled, bool):
        raise ValueError("reporting.primary_score.enabled must be true or false")
    method = str(
        configured_primary.get("method", DEFAULT_PRIMARY_SCORE["method"])
    ).lower()
    if method not in SUPPORTED_PRIMARY_SCORE_METHODS:
        supported = ", ".join(sorted(SUPPORTED_PRIMARY_SCORE_METHODS))
        raise ValueError(
            f"reporting.primary_score.method must be one of: {supported}"
        )
    return {
        "aggregation": {
            "within_document": within,
            "across_documents": across,
            "available_within_document": ["micro", "macro"],
            "across_systems": "none",
        },
        "primary_score": {
            "enabled": enabled,
            "method": method,
        },
    }


def load_reporting_aggregation(path: Path) -> dict[str, Any]:
    """Return aggregation settings for callers using the legacy helper."""
    return load_reporting_config(path)["aggregation"]
