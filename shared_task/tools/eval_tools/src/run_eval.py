"""Run evaluation with the release directory layout."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from runtime_env import ensure_safe_hf_env_for_main

ensure_safe_hf_env_for_main(__name__)

from eval_pair import evaluate_pair
from evaluation_scope import resolve_evaluation_scope
from reporting_config import load_reporting_config


RELEASE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = RELEASE_ROOT / "config" / "evaluation.yaml"
DEFAULT_DATA_DIR = RELEASE_ROOT / "data"
SECTION_RULE = "=" * 60
SUBSECTION_RULE = "-" * 60
GOLD_INPUT_SUFFIX = "-gold.json"
SYSTEM_INPUT_SUFFIX = "-sum.json"
EVAL_OUTPUT_SUFFIX = "-eval"


def display_path(path: Path | str) -> str:
    """Return a path relative to the release root when possible."""
    candidate = Path(path)
    try:
        return str(candidate.resolve().relative_to(RELEASE_ROOT))
    except (OSError, ValueError):
        return str(path)


def relativize_paths(value: Any) -> Any:
    """Convert absolute release-local paths inside a result object."""
    if isinstance(value, dict):
        return {key: relativize_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [relativize_paths(item) for item in value]
    if isinstance(value, str):
        path = Path(value)
        if path.is_absolute():
            return display_path(path)
    return value


def fmt_number(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    if value is None:
        return "not_available"
    return str(value)


def fmt_six_decimals(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{float(value):.6f}"
    if value is None:
        return "not_available"
    return str(value)


def _format_scope_sections(scope: Any) -> str:
    if not isinstance(scope, dict):
        return "all"
    sections = scope.get("sections", "all")
    if isinstance(sections, list):
        return ", ".join(str(section_id) for section_id in sections) or "none"
    return str(sections)


def append_title(lines: list[str], title: str, rule: str = SECTION_RULE) -> None:
    lines.extend([rule, title, rule])


def append_field(lines: list[str], label: str, value: Any) -> None:
    lines.append(f"{label:<20}: {value}")


def load_structure(
    path: Path,
    selected_sections: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "sections": set(),
            "subsections": set(),
            "bullet_count": 0,
        }
    sections: set[str] = set()
    subsections: set[tuple[str, str]] = set()
    bullet_count = 0
    selected = set(selected_sections) if selected_sections is not None else None
    for section in document.get("sections", []) or []:
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("id", "")).strip()
        if selected is not None and section_id not in selected:
            continue
        if section_id:
            sections.add(section_id)
        for bullet in section.get("bullets", []) or []:
            if isinstance(bullet, dict):
                bullet_count += 1
        for subsection in section.get("subsections", []) or []:
            if not isinstance(subsection, dict):
                continue
            subsection_id = str(subsection.get("id", "")).strip()
            if section_id and subsection_id:
                subsections.add((section_id, subsection_id))
            for bullet in subsection.get("bullets", []) or []:
                if isinstance(bullet, dict):
                    bullet_count += 1
    return {
        "sections": sections,
        "subsections": subsections,
        "bullet_count": bullet_count,
    }


def build_structure_summary(
    gold_path: Path,
    system_path: Path,
    evaluation: dict[str, Any] | None = None,
    selected_sections: tuple[str, ...] | None = None,
) -> dict[str, dict[str, int]]:
    gold = load_structure(gold_path, selected_sections)
    system = load_structure(system_path, selected_sections)
    gold_sections = gold["sections"]
    system_sections = system["sections"]
    gold_subsections = gold["subsections"]
    system_subsections = system["subsections"]
    weighted_summary = (
        ((evaluation or {}).get("weighted_alignment") or {}).get("summary") or {}
    )
    matched_bullets = weighted_summary.get("matched_pairs")
    gold_bullets = weighted_summary.get("gold_units", gold["bullet_count"])
    system_bullets = weighted_summary.get("system_units", system["bullet_count"])
    return {
        "sections": {
            "gold": len(gold_sections),
            "system": len(system_sections),
            "matched": len(gold_sections & system_sections),
            "unmatched_gold": len(gold_sections - system_sections),
            "unmatched_system": len(system_sections - gold_sections),
        },
        "subsections": {
            "gold": len(gold_subsections),
            "system": len(system_subsections),
            "matched": len(gold_subsections & system_subsections),
            "unmatched_gold": len(gold_subsections - system_subsections),
            "unmatched_system": len(system_subsections - gold_subsections),
        },
        "bullets": {
            "gold": int(gold_bullets or 0),
            "system": int(system_bullets or 0),
            "matched": int(matched_bullets or 0),
            "unmatched_gold": max(int(gold_bullets or 0) - int(matched_bullets or 0), 0),
            "unmatched_system": max(int(system_bullets or 0) - int(matched_bullets or 0), 0),
        },
    }


def parse_disaster_filename(path: Path, expected_suffix: str | None = None) -> str:
    """Return the disaster ID prefix before a role-specific suffix."""
    suffixes = (expected_suffix,) if expected_suffix else (
        GOLD_INPUT_SUFFIX,
        SYSTEM_INPUT_SUFFIX,
    )
    matching_suffix = next(
        (suffix for suffix in suffixes if path.name.endswith(suffix)),
        None,
    )
    if matching_suffix is None:
        expected = " or ".join(suffixes)
        raise ValueError(
            f"evaluation input filename must end with {expected}: {path.name}"
        )
    disaster_id = path.name[:-len(matching_suffix)].strip()
    if not disaster_id:
        raise ValueError(f"empty disaster ID in filename: {path.name}")
    return disaster_id


def index_disaster_files(directory: Path, expected_suffix: str) -> dict[str, Path]:
    """Index direct JSON files after validating their role-specific suffix."""
    return {
        parse_disaster_filename(path, expected_suffix): path
        for path in sorted(directory.glob("*.json"))
    }


def discover_pairs(sys_dir: Path, gold_dir: Path) -> list[dict[str, Any]]:
    """Match Gold and System files by their shared disaster ID prefix."""
    gold_files = index_disaster_files(gold_dir, GOLD_INPUT_SUFFIX)
    system_files = index_disaster_files(sys_dir, SYSTEM_INPUT_SUFFIX)
    disaster_ids = sorted(set(gold_files) | set(system_files))
    return [
        {
            "file_id": disaster_id,
            "gold_path": gold_files.get(disaster_id),
            "system_path": system_files.get(disaster_id),
        }
        for disaster_id in disaster_ids
    ]


def compact_summary(result: dict[str, Any]) -> dict[str, Any]:
    summary = result.get("summary") or {}
    return {
        "rouge": summary.get("rouge"),
        "bertscore": summary.get("bertscore"),
        "bleurt": summary.get("bleurt"),
        "weighted_alignment": summary.get("weighted_alignment"),
    }


def metric_view(item: dict[str, Any], aggregation: str) -> dict[str, Any]:
    """Return one compact micro or macro metric view for a scored document."""
    summary = item.get("summary") or {}
    rouge = summary.get("rouge") or {}
    bertscore = summary.get("bertscore") or {}
    bleurt = summary.get("bleurt") or {}
    weighted = summary.get("weighted_alignment") or {}
    rouge_values = rouge.get(aggregation) or {}
    bert_values = bertscore.get(aggregation) or {}
    bleurt_values = bleurt.get(aggregation) or {}
    weighted_prefix = "micro" if aggregation == "micro" else "macro"

    def ordered_prf(value: Any, score_field: str) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        return {
            "precision": value.get("precision"),
            "recall": value.get("recall"),
            score_field: value.get(score_field),
        }

    return {
        "rouge1": ordered_prf(rouge_values.get("rouge1"), "fmeasure"),
        "rouge2": ordered_prf(rouge_values.get("rouge2"), "fmeasure"),
        "rougeL": ordered_prf(rouge_values.get("rougeL"), "fmeasure"),
        "bertscore": ordered_prf(bert_values, "f1"),
        "bleurt": {"score": bleurt_values.get("score")},
        "weighted_alignment": {
            "precision": weighted.get(f"{weighted_prefix}_soft_precision"),
            "recall": weighted.get(f"{weighted_prefix}_soft_recall"),
            "f1": weighted.get(f"{weighted_prefix}_soft_f1"),
            "scope": weighted.get("scope"),
            "metric": weighted.get("metric"),
        },
    }


def build_disaster_summary(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build one compact summary row per disaster for a single system."""
    rows: list[dict[str, Any]] = []
    for item in results:
        row: dict[str, Any] = {
            "disaster_id": item.get("file_id"),
            "system_id": item.get("sys_id"),
            "gold_file": item.get("gold_file"),
            "system_file": item.get("system_file"),
            "status": item.get("status"),
        }
        if item.get("status") == "scored":
            row["micro"] = metric_view(item, "micro")
            row["macro"] = metric_view(item, "macro")
        else:
            row["error"] = item.get("error")
            row["micro"] = None
            row["macro"] = None
        rows.append(row)
    return rows


def mean_views(values: list[Any]) -> Any:
    """Recursively average numeric metric leaves across scored disasters."""
    present = [value for value in values if value is not None]
    if not present:
        return None
    if all(isinstance(value, dict) for value in present):
        keys = list(dict.fromkeys(key for value in present for key in value))
        return {key: mean_views([value.get(key) for value in present]) for key in keys}
    numeric = [
        float(value)
        for value in present
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    if len(numeric) == len(present):
        return rounded_mean(numeric)
    unique = list(dict.fromkeys(str(value) for value in present))
    return unique[0] if len(unique) == 1 else unique


def rounded_mean(values: list[float]) -> float:
    """Return a six-decimal arithmetic mean using conventional half-up rounding."""
    mean_value = sum(Decimal(str(value)) for value in values) / Decimal(len(values))
    return float(mean_value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def summary_value(view: dict[str, Any] | None, *path: str) -> Any:
    value: Any = view or {}
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def append_system_summary_table(
    lines: list[str],
    rows: list[dict[str, Any]],
    aggregation: str,
) -> None:
    lines.append(
        f"{'System ID':<12} {'ROUGE-1 F1':>11} {'ROUGE-2 F1':>11} "
        f"{'ROUGE-L F1':>11} {'BERTScore F1':>13} {'BLEURT':>8} "
        f"{'Weighted Align F1':>17}"
    )
    lines.append("-" * 91)
    for row in rows:
        view = row.get(aggregation)
        lines.append(
            f"{str(row.get('system_id', 'unknown')):<12} "
            f"{fmt_number(summary_value(view, 'rouge1', 'fmeasure')):>11} "
            f"{fmt_number(summary_value(view, 'rouge2', 'fmeasure')):>11} "
            f"{fmt_number(summary_value(view, 'rougeL', 'fmeasure')):>11} "
            f"{fmt_number(summary_value(view, 'bertscore', 'f1')):>13} "
            f"{fmt_number(summary_value(view, 'bleurt', 'score')):>8} "
            f"{fmt_number(summary_value(view, 'weighted_alignment', 'f1')):>17}"
        )


def build_combined_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Build one system's overall macro result with equal disaster weight."""
    results = payload.get("results") or []
    scored_results = [item for item in results if item.get("status") == "scored"]
    primary_within = str(
        (payload.get("aggregation") or {}).get("within_document", "micro")
    )
    overall_macro = mean_views([
        metric_view(item, primary_within) for item in scored_results
    ])
    bertscore_f1 = summary_value(overall_macro, "bertscore", "f1")
    bleurt_score = summary_value(overall_macro, "bleurt", "score")
    primary_components = [bertscore_f1, bleurt_score]
    primary_score = (
        rounded_mean([float(value) for value in primary_components])
        if all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in primary_components
        )
        else None
    )
    primary_score_config = payload.get("primary_score_config") or {
        "enabled": True,
        "method": "mean_bertscore_f1_bleurt",
    }
    primary_score_enabled = primary_score_config.get("enabled", True)
    primary_score_method = str(
        primary_score_config.get("method", "mean_bertscore_f1_bleurt")
    )
    if primary_score_method != "mean_bertscore_f1_bleurt":
        raise ValueError(
            "unsupported primary score method: "
            f"{primary_score_method}"
        )
    total_count = len(results)
    scored_count = len(scored_results)
    disaster_ids = [
        str(item.get("file_id"))
        for item in results
        if item.get("file_id") is not None
    ]
    combined = {
        "generated_at_utc": payload["generated_at_utc"],
        "config": payload["config"],
        "gold_dir": payload["gold_dir"],
        "system_dir": payload["system_dir"],
        "system_id": payload["system_id"],
        "evaluation_scope": payload.get("evaluation_scope", {"sections": "all"}),
        "aggregation": {
            "level": "across_disasters",
            "method": "macro",
            "note": (
                "Overall macro results are the equal-weight mean of the selected "
                "overall result from each scored disaster."
            ),
        },
        "disaster_count": total_count,
        "scored_disaster_count": scored_count,
        "disaster_ids": disaster_ids,
        "coverage_ratio": round(scored_count / total_count, 6) if total_count else None,
        "failed_disasters": [
            {
                "disaster_id": item.get("file_id"),
                "status": item.get("status"),
                "error": item.get("error"),
            }
            for item in results
            if item.get("status") != "scored"
        ],
        "overall_macro": overall_macro,
    }
    if primary_score_enabled and primary_score_is_required(payload):
        combined["primary_score"] = {
            "method": primary_score_method,
            "components": {
                "bertscore_f1": bertscore_f1,
                "bleurt": bleurt_score,
            },
            "score": primary_score,
        }
    return combined


def primary_score_is_required(payload: dict[str, Any]) -> bool:
    """Return whether this run is expected to produce one release primary score."""
    primary_config = payload.get("primary_score_config") or {}
    if not primary_config.get("enabled", True):
        return False
    views = {
        str(evaluation.get("view", "single"))
        for item in payload.get("results") or []
        if item.get("status") == "scored"
        and isinstance((evaluation := item.get("evaluation")), dict)
    }
    # Sweep runs expose multiple configurations and therefore do not define one
    # release primary score. Callers without an explicit view are treated as a
    # normal single-configuration run.
    return not views or views == {"single"}


def _active_metric_failures(value: Any, path: str) -> list[str]:
    """Collect active metric blocks that did not finish with a scored status."""
    if not isinstance(value, dict) or not value:
        return [f"{path}: missing metric result"]
    if value.get("mode") == "disabled":
        return []
    if "status" in value:
        status = value.get("status")
        if status == "scored":
            return []
        detail = f"{path}: status={status or 'missing'}"
        if value.get("reason"):
            detail += f", reason={value['reason']}"
        if value.get("error"):
            detail += f", error={value['error']}"
        return [detail]

    children = [
        (str(key), child)
        for key, child in value.items()
        if isinstance(child, dict)
    ]
    if not children:
        return [f"{path}: active metric result has no status"]
    failures: list[str] = []
    for key, child in children:
        failures.extend(_active_metric_failures(child, f"{path}.{key}"))
    return failures


def evaluation_metric_failures(
    evaluation: Any,
    disaster_id: str,
) -> list[str]:
    """Return active metric failures for one disaster evaluation."""
    if not isinstance(evaluation, dict):
        return [f"{disaster_id}: missing evaluation result"]
    failures = _active_metric_failures(
        evaluation.get("configured_metrics"),
        f"{disaster_id}.configured_metrics",
    )
    failures.extend(_active_metric_failures(
        evaluation.get("weighted_alignment"),
        f"{disaster_id}.weighted_alignment",
    ))
    return failures


def collect_evaluation_failures(
    payload: dict[str, Any],
    combined: dict[str, Any],
) -> list[str]:
    """Return reasons that make a completed evaluator run operationally incomplete."""
    failures: list[str] = []
    for item in payload.get("results") or []:
        disaster_id = str(item.get("file_id", "unknown"))
        status = item.get("status")
        if status != "scored":
            detail = f"{disaster_id}: status={status or 'missing'}"
            if item.get("error"):
                detail += f", error={item['error']}"
            failures.append(detail)
            continue

        failures.extend(evaluation_metric_failures(
            item.get("evaluation"), disaster_id,
        ))

    if primary_score_is_required(payload):
        primary = combined.get("primary_score") or {}
        score = primary.get("score")
        valid_score = (
            isinstance(score, (int, float))
            and not isinstance(score, bool)
            and math.isfinite(float(score))
        )
        if not valid_score:
            failures.append("combined.primary_score.score is not available")
    return failures


def build_combined_log(payload: dict[str, Any]) -> str:
    """Build one system's overall across-disaster macro report."""
    aggregation = payload.get("aggregation") or {}
    disaster_ids = ", ".join(
        str(value) for value in payload.get("disaster_ids") or []
    ) or "none"
    lines = [
        SECTION_RULE,
        "Combined Multi-disaster Evaluation Log",
        SECTION_RULE,
        "",
        f"System ID       : {payload.get('system_id')}",
        f"Gold directory  : {payload.get('gold_dir')}",
        f"System directory: {payload.get('system_dir')}",
        f"Sections        : {_format_scope_sections(payload.get('evaluation_scope'))}",
        (
            f"Coverage        : {payload.get('scored_disaster_count', 0)}/"
            f"{payload.get('disaster_count', 0)} scored disasters"
        ),
        f"Disaster IDs    : {disaster_ids}",
        "",
        "Aggregation:",
        f"  level : {aggregation.get('level', 'across_disasters')}",
        f"  method: {aggregation.get('method', 'macro')}",
        f"  note  : {aggregation.get('note', '')}",
        "",
        SECTION_RULE,
        "Overall Macro Results",
        SECTION_RULE,
    ]
    append_system_summary_table(
        lines,
        [{
            "system_id": payload.get("system_id"),
            "overall_macro": payload.get("overall_macro"),
        }],
        "overall_macro",
    )
    primary_score = payload.get("primary_score")
    if isinstance(primary_score, dict):
        components = primary_score.get("components") or {}
        lines.extend([
            "",
            SECTION_RULE,
            "Primary Score",
            SECTION_RULE,
            f"{'Method':<16}: {primary_score.get('method', 'not_available')}",
            (
                f"{'BERTScore F1':<16}: "
                f"{fmt_six_decimals(components.get('bertscore_f1'))}"
            ),
            f"{'BLEURT':<16}: {fmt_six_decimals(components.get('bleurt'))}",
            f"{'Score':<16}: {fmt_six_decimals(primary_score.get('score'))}",
        ])
    if payload.get("failed_disasters"):
        lines.extend(["", "Coverage Warnings:"])
        lines.extend(
            f"- {item.get('disaster_id')}: {item.get('status')} ({item.get('error')})"
            for item in payload["failed_disasters"]
        )
    return "\n".join(lines).rstrip() + "\n"


def _strip_unselected_pair_aggregates(value: Any, selected: str) -> Any:
    """Remove the unselected within-document aggregate from pair output."""
    excluded = "macro" if selected == "micro" else "micro"
    if isinstance(value, dict):
        return {
            key: _strip_unselected_pair_aggregates(item, selected)
            for key, item in value.items()
            if key != excluded and not key.startswith(f"{excluded}_")
        }
    if isinstance(value, list):
        return [
            _strip_unselected_pair_aggregates(item, selected)
            for item in value
        ]
    return value


def build_pair_output_payload(payload: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """Build one disaster payload containing only its selected aggregation."""
    selected = str((payload.get("aggregation") or {}).get("within_document", "micro"))
    return {
        "generated_at_utc": payload["generated_at_utc"],
        "config": payload["config"],
        "gold_dir": payload["gold_dir"],
        "system_dir": payload["system_dir"],
        "system_id": payload["system_id"],
        "evaluation_scope": payload.get("evaluation_scope", {"sections": "all"}),
        "disaster_id": item.get("file_id"),
        "aggregation": {
            "level": "within_document",
            "method": selected,
        },
        "results": [_strip_unselected_pair_aggregates(item, selected)],
    }


def write_system_outputs(payload: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    """Write one JSON/log pair per disaster plus one combined pair."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for pattern in (
        f"*{EVAL_OUTPUT_SUFFIX}.json",
        f"*{EVAL_OUTPUT_SUFFIX}.log",
        "*.eval.json",
        "*.eval.log",
        "combined.json",
        "combined.log",
    ):
        for stale_path in out_dir.glob(pattern):
            stale_path.unlink()
    for item in payload.get("results") or []:
        disaster_payload = build_pair_output_payload(payload, item)
        stem = str(item.get("file_id"))
        (out_dir / f"{stem}{EVAL_OUTPUT_SUFFIX}.json").write_text(
            json.dumps(disaster_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (out_dir / f"{stem}{EVAL_OUTPUT_SUFFIX}.log").write_text(
            build_log(disaster_payload),
            encoding="utf-8",
        )
    combined = build_combined_payload(payload)
    (out_dir / f"combined{EVAL_OUTPUT_SUFFIX}.json").write_text(
        json.dumps(combined, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / f"combined{EVAL_OUTPUT_SUFFIX}.log").write_text(
        build_combined_log(combined),
        encoding="utf-8",
    )
    return combined


def append_metric_summary(
    lines: list[str],
    item: dict[str, Any],
    primary_aggregation: str = "micro",
) -> None:
    summary = item.get("summary") or {}
    rouge = summary.get("rouge") or {}
    bertscore = summary.get("bertscore") or {}
    bleurt = summary.get("bleurt") or {}
    weighted = summary.get("weighted_alignment") or {}
    structure = item.get("structure_summary") or {}
    bullet_summary = structure.get("bullets") or {}
    rouge_mode = str(rouge.get("mode", "not_available")).title()
    bertscore_mode = str(bertscore.get("mode", "not_available")).title()
    bleurt_mode = str(bleurt.get("mode", "not_available")).title()
    bullet_mode = str(weighted.get("scope", "not_available")).title()

    append_title(lines, "Evaluation Summary")
    lines.append("Text-level Evaluation")
    lines.append("")
    lines.append(f"ROUGE ({rouge_mode})")
    for label, key in (
        ("ROUGE-1 F1", "rouge1"),
        ("ROUGE-2 F1", "rouge2"),
        ("ROUGE-L F1", "rougeL"),
    ):
        lines.append(f"  {label:<12}: {fmt_number((rouge.get(key) or {}).get('fmeasure'))}")
    lines.append("")

    lines.append(f"BERTScore ({bertscore_mode})")
    lines.append(f"  {'Precision':<12}: {fmt_number(bertscore.get('precision'))}")
    lines.append(f"  {'Recall':<12}: {fmt_number(bertscore.get('recall'))}")
    lines.append(f"  {'F1':<12}: {fmt_number(bertscore.get('f1'))}")
    lines.append("")

    lines.append(f"BLEURT ({bleurt_mode})")
    lines.append(f"  {'Score':<12}: {fmt_number(bleurt.get('score'))}")
    lines.append("")
    lines.append(SUBSECTION_RULE)
    lines.append("")

    metric = weighted.get("metric", "not_available")
    tweet_config = (
        ((item.get("evaluation") or {}).get("weighted_alignment") or {})
        .get("configuration", {})
        .get("tweet_id_overlap", {})
    )
    if tweet_config.get("enabled"):
        metric_label = f"{metric} + Tweet-ID overlap"
    else:
        metric_label = str(metric)

    lines.append(f"Bullet-level Hungarian Alignment ({bullet_mode})")
    lines.append("")
    append_field(lines, "Similarity metric", metric_label)
    append_field(lines, "Soft Precision", fmt_number(weighted.get("micro_soft_precision")))
    append_field(lines, "Soft Recall", fmt_number(weighted.get("micro_soft_recall")))
    append_field(lines, "Soft F1", fmt_number(weighted.get("micro_soft_f1")))
    lines.append("")
    append_field(lines, "Matched pairs", weighted.get("matched_pairs"))
    append_field(lines, "Unmatched gold", bullet_summary.get("unmatched_gold", 0))
    append_field(lines, "Unmatched system", bullet_summary.get("unmatched_system", 0))
    lines.append("")
    selected = primary_aggregation if primary_aggregation in {"micro", "macro"} else "micro"
    lines.append(f"Within-document {selected.title()} (Primary)")
    append_system_summary_table(lines, build_disaster_summary([item]), selected)
    lines.append("")


def append_structure_summary(lines: list[str], summary: dict[str, dict[str, int]]) -> None:
    append_title(lines, "Structure Summary")
    for key in ("sections", "subsections", "bullets"):
        values = summary.get(key) or {}
        lines.append(
            f"{key}: "
            f"gold={values.get('gold', 0)} "
            f"system={values.get('system', 0)} "
            f"matched={values.get('matched', 0)} "
            f"unmatched_gold={values.get('unmatched_gold', 0)} "
            f"unmatched_system={values.get('unmatched_system', 0)}"
        )


def iter_metric_blocks(value: Any, prefix: str = ""):
    if isinstance(value, dict) and "diagnostics" in value:
        yield prefix.rstrip("."), value
        return
    if isinstance(value, dict):
        for key in sorted(value):
            next_prefix = f"{prefix}{key}."
            yield from iter_metric_blocks(value[key], next_prefix)


def append_rouge_diagnostics(lines: list[str], evaluation: dict[str, Any]) -> None:
    rouge_blocks = list(iter_metric_blocks(
        (evaluation.get("configured_metrics") or {}).get("rouge") or {},
        "rouge.",
    ))
    append_title(lines, "ROUGE Diagnostics")
    if not rouge_blocks:
        lines.append("none")
        return
    for label, block in rouge_blocks:
        diagnostics = block.get("diagnostics") or {}
        scope = block.get("mode") or label.replace("rouge.", "").strip(".") or "unknown"
        matched_units = int(diagnostics.get("matched_units", 0))
        skipped_both_empty = int(diagnostics.get("skipped_both_empty_units", 0))
        scored_units = int(diagnostics.get("scored_units", 0))
        lines.append(
            f"{scope}: "
            f"gold_units={diagnostics.get('gold_units', 0)} "
            f"system_units={diagnostics.get('system_units', 0)} "
            f"matched_units={matched_units} "
            f"scored_units={scored_units} "
            f"skipped_both_empty={skipped_both_empty}"
        )
        lines.append(
            f"  denominator_policy={diagnostics.get('denominator_policy', 'matched_only')}"
        )
        for metric in ("rouge1", "rouge2"):
            counts = diagnostics.get(metric) or {}
            lines.append(
                f"  {metric}: "
                f"gold_ngrams={counts.get('gold_ngrams', 0)} "
                f"system_ngrams={counts.get('system_ngrams', 0)} "
                f"overlapping_ngrams={counts.get('overlapping_ngrams', 0)}"
            )
        rouge_l = diagnostics.get("rougeL") or {}
        if rouge_l:
            lines.append(
                "  rougeL: "
                f"gold_tokens={rouge_l.get('gold_tokens', 0)} "
                f"system_tokens={rouge_l.get('system_tokens', 0)} "
                f"total_lcs_length={rouge_l.get('total_lcs_length', 0)}"
            )


def format_item(item: dict[str, Any]) -> str:
    item_id = item.get("bullet_id")
    text = " ".join(str(item.get("text", "")).split())
    return f'id={item_id if item_id is not None else "unknown"} text="{text}"'


def append_unmatched_items(lines: list[str], label: str, items: list[dict[str, Any]]) -> None:
    if not items:
        lines.append(f"  {label}: none")
        return
    lines.append(f"  {label}:")
    for item in items:
        lines.append(f"  - {format_item(item)}")


def missing_tweet_id_counts(weighted: dict[str, Any]) -> dict[str, int] | None:
    tweet_config = ((weighted.get("configuration") or {}).get("tweet_id_overlap") or {})
    if not tweet_config.get("enabled"):
        return None
    counts = {"gold": 0, "system": 0}
    for group in weighted.get("groups") or []:
        for pair in group.get("pairs") or []:
            if not pair.get("gold_tweet_ids"):
                counts["gold"] += 1
            if not pair.get("system_tweet_ids"):
                counts["system"] += 1
        for item in group.get("unmatched_gold") or []:
            if not item.get("tweet_ids"):
                counts["gold"] += 1
        for item in group.get("unmatched_system") or []:
            if not item.get("tweet_ids"):
                counts["system"] += 1
    return counts


def append_alignment_log(lines: list[str], result: dict[str, Any]) -> None:
    weighted = result.get("weighted_alignment") or {}
    groups = weighted.get("groups") or []
    append_title(lines, "Alignment Details")
    if not groups:
        lines.append("no group-level detail available")
        return

    configuration = weighted.get("configuration") or {}
    text_metric = weighted.get("metric") or configuration.get("metric") or "unknown"
    tweet_config = configuration.get("tweet_id_overlap") or {}
    tweet_overlap_enabled = bool(tweet_config.get("enabled"))
    text_weight = tweet_config.get("text_weight")
    for index, group in enumerate(groups):
        if index:
            lines.append("")
        group_id = group.get("group_id")
        lines.append(f"Group {group_id}")
        lines.append(
            "  "
            f"gold={group.get('gold_count')} "
            f"system={group.get('system_count')} "
            f"matched={group.get('matched_count')} "
            f"soft_f1={fmt_number(group.get('soft_f1'))}"
        )
        pairs = group.get("pairs") or []
        if pairs:
            lines.append("  matched_pairs:")
        else:
            lines.append("  matched_pairs: none")
        for pair in pairs:
            gold_text = " ".join(str(pair.get("gold_text", "")).split())
            system_text = " ".join(str(pair.get("system_text", "")).split())
            lines.append(
                "  - "
                f"gold={pair.get('gold_bullet_id')} "
                f"system={pair.get('system_bullet_id')}"
            )
            tweet_similarity = pair.get("tweet_id_similarity")
            if not tweet_overlap_enabled:
                tweet_value = "not_used"
            elif tweet_similarity is None:
                tweet_value = "not_available"
            else:
                tweet_value = fmt_number(tweet_similarity)
            lines.append(
                "    "
                f"text_metric={text_metric} "
                f"text_similarity={fmt_number(pair.get('text_similarity'))} "
                f"tweet_id_jaccard={tweet_value} "
                f"text_weight={fmt_number(text_weight) if tweet_overlap_enabled else 'not_used'} "
                f"final_edge_score={fmt_number(pair.get('weight'))}"
            )
            lines.append(f"    gold_text={gold_text}")
            lines.append(f"    system_text={system_text}")
        append_unmatched_items(lines, "unmatched_gold", group.get("unmatched_gold") or [])
        append_unmatched_items(lines, "unmatched_system", group.get("unmatched_system") or [])


def collect_metric_statuses(value: Any, prefix: str = "") -> list[str]:
    statuses: list[str] = []
    if isinstance(value, dict) and "status" in value:
        status = value.get("status")
        if status not in {None, "scored"}:
            statuses.append(
                f"{prefix.rstrip('.') or 'metric'} status={status} "
                f"reason={value.get('reason', 'not_available')}"
            )
        return statuses
    if isinstance(value, dict):
        for key in sorted(value):
            statuses.extend(collect_metric_statuses(value[key], f"{prefix}{key}."))
    return statuses


def collect_warnings(value: Any) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if isinstance(value.get("warnings"), list):
            warnings.extend(value["warnings"])
        for item in value.values():
            warnings.extend(collect_warnings(item))
    elif isinstance(value, list):
        for item in value:
            warnings.extend(collect_warnings(item))
    return warnings


def append_warning_summary(lines: list[str], item: dict[str, Any]) -> None:
    evaluation = item.get("evaluation") or {}
    metrics = evaluation.get("configured_metrics") or {}
    weighted = evaluation.get("weighted_alignment") or {}
    warnings = collect_warnings(evaluation)
    missing_structure = [
        warning for warning in warnings
        if "missing" in str(warning.get("code", "")) and "structure" in str(warning.get("code", ""))
    ]
    skipped_both_empty = 0
    for _, block in iter_metric_blocks(metrics.get("rouge") or {}, "rouge."):
        skipped_both_empty += int((block.get("diagnostics") or {}).get(
            "skipped_both_empty_units", 0
        ))
    metric_statuses = collect_metric_statuses(metrics)
    if weighted.get("status") not in {None, "scored"}:
        metric_statuses.append(
            f"weighted_alignment status={weighted.get('status')} "
            f"reason={weighted.get('reason', 'not_available')}"
        )
    tweet_missing = missing_tweet_id_counts(weighted)
    append_title(lines, "Warnings")
    lines.append(
        "missing_structure: "
        + ("none" if not missing_structure else "; ".join(
            f"{warning.get('side', 'input')}:{warning.get('code')}"
            for warning in missing_structure
        ))
    )
    lines.append(f"skipped_both_empty_units={skipped_both_empty}")
    if tweet_missing is None:
        lines.append("missing_tweet_ids: not_used")
    else:
        lines.append(
            "missing_tweet_ids: "
            f"gold_units={tweet_missing['gold']} system_units={tweet_missing['system']}"
        )
    skipped_groups = [
        group.get("group_id", "unknown")
        for group in weighted.get("groups") or []
        if group.get("status") == "skipped"
    ]
    lines.append(
        "skipped_groups: "
        + ("none" if not skipped_groups else ", ".join(skipped_groups))
    )
    lines.append(
        "metric_failures: "
        + ("none" if not metric_statuses else "; ".join(metric_statuses))
    )
    lines.append(
        "warnings: "
        + ("none" if not warnings else "; ".join(
            str(warning.get("code", "unknown")) for warning in warnings
        ))
    )


def build_log(payload: dict[str, Any]) -> str:
    aggregation = payload.get("aggregation") or {}
    primary_aggregation = str(
        aggregation.get("within_document", aggregation.get("method", "micro"))
    )
    lines = [
        SECTION_RULE,
        "LT4CPR Evaluation Log",
        SECTION_RULE,
        "",
        f"Generated at UTC : {payload['generated_at_utc']}",
        f"Config           : {payload['config']}",
        f"Sections         : {_format_scope_sections(payload.get('evaluation_scope'))}",
        "",
    ]
    for index, item in enumerate(payload["results"]):
        if index:
            lines.append("")
        append_field(lines, "Disaster ID", item["file_id"])
        append_field(lines, "System ID", item["sys_id"])
        lines.append("")
        append_field(lines, "Gold", item["gold_file"])
        append_field(lines, "System", item["system_file"])
        lines.append("")
        if item.get("status") != "scored":
            append_title(lines, "Evaluation Summary")
            append_field(lines, "Status", item.get("status"))
            append_field(lines, "Error", item.get("error"))
            lines.append("")
            continue

        append_metric_summary(lines, item, primary_aggregation)
        append_structure_summary(lines, item.get("structure_summary") or {})
        lines.append("")
        append_rouge_diagnostics(lines, item["evaluation"])
        lines.append("")
        append_alignment_log(lines, item["evaluation"])
        lines.append("")
        append_warning_summary(lines, item)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate one system directory against a gold directory across all "
            "disaster files, then write per-disaster and combined reports."
        )
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--sys-dir",
        type=Path,
        default=None,
        help="One system's directory containing one JSON file per disaster.",
    )
    parser.add_argument(
        "--gold-dir",
        type=Path,
        default=None,
        help="Gold directory containing one JSON file per disaster.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory (default: <data-dir>/eval-result/<system-id>).",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--sections",
        default=None,
        help="Comma-separated section IDs to evaluate, or 'all' (overrides config).",
    )
    parser.add_argument(
        "--system-id",
        default=None,
        help=(
            "System label for reports. Defaults to the --sys-dir directory name. "
            "If --sys-dir is omitted, selects <data-dir>/sysId-output/<system-id>."
        ),
    )
    parser.add_argument(
        "--all-modes",
        action="store_true",
        help="Evaluate document, section, and subsection levels.",
    )
    parser.add_argument(
        "--all-config",
        action="store_true",
        help="Sweep all supported metric/level/unit combinations.",
    )
    parser.add_argument(
        "--no-full",
        action="store_true",
        help="Do not include per-group alignment detail in eval.json/eval.log.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_dir = args.data_dir
    gold_dir = args.gold_dir or data_dir / "gold-output"
    if args.sys_dir is not None:
        sys_dir = args.sys_dir
        system_id = args.system_id or sys_dir.name
    elif args.system_id:
        system_id = args.system_id
        sys_dir = data_dir / "sysId-output" / system_id
    else:
        raise SystemExit("provide --sys-dir or --system-id")
    out_dir = args.out_dir or data_dir / "eval-result" / system_id

    if not sys_dir.is_dir():
        raise SystemExit(f"system output directory not found: {sys_dir}")
    if not gold_dir.is_dir():
        raise SystemExit(f"gold output directory not found: {gold_dir}")
    if not args.config.is_file():
        raise SystemExit(f"evaluation config not found: {args.config}")
    try:
        evaluation_scope = resolve_evaluation_scope(args.config, args.sections)
    except ValueError as exc:
        raise SystemExit(f"invalid evaluation scope: {exc}") from exc

    try:
        pairs = discover_pairs(sys_dir, gold_dir)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if not pairs:
        raise SystemExit(
            f"no disaster JSON files found in {gold_dir} or {sys_dir}"
        )

    results: list[dict[str, Any]] = []
    for pair in pairs:
        gold_path = pair["gold_path"]
        system_path = pair["system_path"]
        item: dict[str, Any] = {
            "file_id": pair["file_id"],
            "sys_id": system_id,
            "gold_file": display_path(gold_path) if gold_path else None,
            "system_file": display_path(system_path) if system_path else None,
        }
        if gold_path is None:
            item.update({
                "status": "missing_gold",
                "error": f"missing gold file for disaster: {pair['file_id']}",
            })
            results.append(item)
            continue
        if system_path is None:
            item.update({
                "status": "missing_system",
                "error": f"missing system file for disaster: {pair['file_id']}",
            })
            results.append(item)
            continue
        try:
            evaluation = evaluate_pair(
                gold_path,
                system_path,
                args.config,
                include_group_detail=not args.no_full,
                all_modes=args.all_modes,
                all_config=args.all_config,
                evaluation_scope=evaluation_scope,
            )
        except (SystemExit, Exception) as exc:  # noqa: BLE001
            item.update({"status": "error", "error": str(exc)})
        else:
            evaluation = relativize_paths(evaluation)
            metric_failures = evaluation_metric_failures(
                evaluation, str(pair["file_id"]),
            )
            structure_summary = build_structure_summary(
                gold_path,
                system_path,
                evaluation,
                selected_sections=evaluation_scope.section_ids,
            )
            item.update({
                "status": "scored" if not metric_failures else "incomplete",
                "summary": compact_summary(evaluation),
                "evaluation": evaluation,
                "structure_summary": structure_summary,
                "diagnostics": {"structure_summary": structure_summary},
            })
            if metric_failures:
                item["metric_failures"] = metric_failures
                item["error"] = "; ".join(metric_failures)
        results.append(item)

    reporting = load_reporting_config(args.config)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "config": display_path(args.config),
        "data_dir": display_path(data_dir),
        "gold_dir": display_path(gold_dir),
        "system_dir": display_path(sys_dir),
        "system_id": system_id,
        "evaluation_scope": evaluation_scope.as_dict(),
        "aggregation": reporting["aggregation"],
        "primary_score_config": reporting["primary_score"],
        "results": results,
    }
    combined = write_system_outputs(payload, out_dir)
    print(
        f"[run_eval] wrote {len(results)} per-disaster JSON/log pairs and "
        f"combined{EVAL_OUTPUT_SUFFIX}.json/log under {out_dir}"
    )
    failures = collect_evaluation_failures(payload, combined)
    if failures:
        print("[run_eval] incomplete evaluation:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
