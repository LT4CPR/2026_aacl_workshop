"""Evaluate one gold/system SITREP pair."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime_env import ensure_safe_hf_env_for_main

ensure_safe_hf_env_for_main(__name__)

from eval_sitrep import (
    DEFAULT_EVAL_CONFIG,
    evaluate_configured_pair,
    evaluate_metric_pair,
    load_evaluation_config,
)
from eval_weighted_alignment import (
    evaluate_weighted_alignment_pair,
    slim_weighted_alignment_result,
    weighted_alignment_enabled,
)
from evaluation_scope import EvaluationScope, resolve_evaluation_scope

EVAL_DIR = Path(__file__).resolve().parent
LEVEL_NAMES = {1: "document", 2: "section", 3: "subsection"}
ALL_MODE_METRICS = ("rouge", "bertscore", "bleurt")
ALL_CONFIG_TEXT_METRICS = ("rouge", "bertscore", "bleurt")
ALL_CONFIG_BULLET_METRICS = ("rougeL", "bertscore", "cosine")
ALL_CONFIG_UNIT_MODES = ("bullet", "text")
ALL_CONFIG_TWEET_OVERLAP = (("off", False), ("on", True))


def evaluate_pair(
    gold_path: Path,
    system_path: Path,
    config_path: Path = DEFAULT_EVAL_CONFIG,
    *,
    include_group_detail: bool = False,
    enforce_structure: bool = True,
    all_modes: bool = False,
    all_config: bool = False,
    evaluation_scope: EvaluationScope | None = None,
) -> dict[str, Any]:
    """Run enabled metrics and return one result."""
    for label, path in (("gold", gold_path), ("system", system_path)):
        if not path.exists():
            raise SystemExit(f"[eval_pair] {label} file not found: {path}")

    scope = evaluation_scope or resolve_evaluation_scope(config_path)

    if all_config:
        return evaluate_pair_all_config(
            gold_path,
            system_path,
            config_path,
            include_group_detail=include_group_detail,
            enforce_structure=enforce_structure,
            evaluation_scope=scope,
        )

    if all_modes:
        return evaluate_pair_all_modes(
            gold_path,
            system_path,
            config_path,
            include_group_detail=include_group_detail,
            enforce_structure=enforce_structure,
            evaluation_scope=scope,
        )

    configured_metrics = evaluate_configured_pair(
        system_path, gold_path, config_path, scope,
    )
    payload: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "gold": str(gold_path),
        "system": str(system_path),
        "config": str(config_path),
        "view": "single",
        "evaluation_scope": scope.as_dict(),
        "configured_metrics": configured_metrics["metrics"],
    }

    if weighted_alignment_enabled(config_path):
        try:
            weighted = evaluate_weighted_alignment_pair(
                gold_path,
                system_path,
                config_path,
                enforce_structure=enforce_structure,
                evaluation_scope=scope,
            )
            payload["weighted_alignment"] = slim_weighted_alignment_result(
                weighted,
                include_groups=include_group_detail,
            )
        except (SystemExit, Exception) as exc:  # noqa: BLE001
            payload["weighted_alignment"] = _weighted_failure_block(exc)
    else:
        payload["weighted_alignment"] = {"mode": "disabled"}

    payload["summary"] = build_flat_summary(payload)
    return payload


def _weighted_failure_block(exc: BaseException, *, scope: str | None = None) -> dict[str, Any]:
    """Represent a skipped alignment path."""
    message = str(exc)
    return {
        "status": "skipped",
        "reason": "invalid_or_unavailable_structure",
        "scope": scope,
        "error": message,
        "warnings": [{
            "code": "invalid_or_unavailable_structure",
            "message": message,
        }],
        "summary": {
            "micro_soft_precision": None,
            "micro_soft_recall": None,
            "micro_soft_f1": None,
            "warning_count": 1,
        },
    }


def evaluate_pair_all_modes(
    gold_path: Path,
    system_path: Path,
    config_path: Path,
    *,
    include_group_detail: bool = False,
    enforce_structure: bool = True,
    evaluation_scope: EvaluationScope | None = None,
) -> dict[str, Any]:
    scope = evaluation_scope or resolve_evaluation_scope(config_path)
    config = load_evaluation_config(config_path)
    configured_metrics: dict[str, Any] = {}
    for name in ALL_MODE_METRICS:
        configured_metrics[name] = {}
        for mode, level in LEVEL_NAMES.items():
            spec = {**config[name], "mode": mode}
            try:
                configured_metrics[name][level] = evaluate_metric_pair(
                    system_path, gold_path, name, spec, scope.section_ids,
                )
            except (SystemExit, Exception) as exc:  # noqa: BLE001
                configured_metrics[name][level] = {
                    "mode": level,
                    "status": "skipped",
                    "reason": "invalid_input_json",
                    "error": str(exc),
                    "warnings": [{"code": "invalid_input_json", "message": str(exc)}],
                }

    weighted_alignment: dict[str, Any] = {}
    if weighted_alignment_enabled(config_path):
        for mode, level in LEVEL_NAMES.items():
            try:
                weighted = evaluate_weighted_alignment_pair(
                    gold_path,
                    system_path,
                    config_path,
                    alignment_mode=mode,
                    enforce_structure=enforce_structure,
                    evaluation_scope=scope,
                )
                weighted_alignment[level] = slim_weighted_alignment_result(
                    weighted,
                    include_groups=include_group_detail,
                )
            except (SystemExit, Exception) as exc:  # noqa: BLE001
                weighted_alignment[level] = _weighted_failure_block(exc, scope=level)
    else:
        weighted_alignment = {"mode": "disabled"}

    payload: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "gold": str(gold_path),
        "system": str(system_path),
        "config": str(config_path),
        "view": "all_modes",
        "evaluation_scope": scope.as_dict(),
        "configured_metrics": configured_metrics,
        "weighted_alignment": weighted_alignment,
    }
    payload["summary"] = build_all_modes_summary(payload)
    return payload


def _run_text_level_sweep(
    gold_path: Path,
    system_path: Path,
    config: dict[str, Any],
    *,
    metrics: tuple[str, ...] = ALL_CONFIG_TEXT_METRICS,
    evaluation_scope: EvaluationScope,
) -> dict[str, Any]:
    configured_metrics: dict[str, Any] = {}
    for name in metrics:
        configured_metrics[name] = {}
        for mode, level in LEVEL_NAMES.items():
            spec = {**config[name], "mode": mode}
            try:
                configured_metrics[name][level] = evaluate_metric_pair(
                    system_path, gold_path, name, spec,
                    evaluation_scope.section_ids,
                )
            except (SystemExit, Exception) as exc:  # noqa: BLE001
                configured_metrics[name][level] = {
                    "mode": level,
                    "status": "skipped",
                    "reason": "invalid_input_json",
                    "error": str(exc),
                    "warnings": [{"code": "invalid_input_json", "message": str(exc)}],
                }
    return configured_metrics


def _run_bullet_level_sweep(
    gold_path: Path,
    system_path: Path,
    config_path: Path,
    *,
    include_group_detail: bool = False,
    enforce_structure: bool = True,
    evaluation_scope: EvaluationScope,
) -> dict[str, Any]:
    weighted_alignment: dict[str, Any] = {}
    if not weighted_alignment_enabled(config_path):
        return {"mode": "disabled"}

    for mode, level in LEVEL_NAMES.items():
        weighted_alignment[level] = {}
        for unit_mode in ALL_CONFIG_UNIT_MODES:
            weighted_alignment[level][unit_mode] = {}
            for metric in ALL_CONFIG_BULLET_METRICS:
                weighted_alignment[level][unit_mode][metric] = {}
                for overlap_label, overlap_enabled in ALL_CONFIG_TWEET_OVERLAP:
                    try:
                        weighted = evaluate_weighted_alignment_pair(
                            gold_path,
                            system_path,
                            config_path,
                            alignment_mode=mode,
                            unit_mode=unit_mode,
                            metric=metric,
                            tweet_id_overlap_enabled=overlap_enabled,
                            enforce_structure=enforce_structure,
                            evaluation_scope=evaluation_scope,
                        )
                        weighted_alignment[level][unit_mode][metric][overlap_label] = (
                            slim_weighted_alignment_result(
                                weighted,
                                include_groups=include_group_detail,
                            )
                        )
                    except (SystemExit, Exception) as exc:  # noqa: BLE001
                        failure = _weighted_failure_block(exc, scope=level)
                        weighted_alignment[level][unit_mode][metric][overlap_label] = {
                            **failure,
                            "metric": metric,
                            "unit_mode": unit_mode,
                            "tweet_overlap": overlap_label,
                        }
    return weighted_alignment


def evaluate_pair_all_config(
    gold_path: Path,
    system_path: Path,
    config_path: Path,
    *,
    include_group_detail: bool = False,
    enforce_structure: bool = True,
    evaluation_scope: EvaluationScope | None = None,
) -> dict[str, Any]:
    scope = evaluation_scope or resolve_evaluation_scope(config_path)
    config = load_evaluation_config(config_path)
    configured_metrics = _run_text_level_sweep(
        gold_path, system_path, config, evaluation_scope=scope,
    )
    weighted_alignment = _run_bullet_level_sweep(
        gold_path,
        system_path,
        config_path,
        include_group_detail=include_group_detail,
        enforce_structure=enforce_structure,
        evaluation_scope=scope,
    )

    payload: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "gold": str(gold_path),
        "system": str(system_path),
        "config": str(config_path),
        "view": "all_config",
        "evaluation_scope": scope.as_dict(),
        "sweep_axes": {
            "text_level": {
                "metrics": list(ALL_CONFIG_TEXT_METRICS),
                "levels": list(LEVEL_NAMES.values()),
            },
            "bullet_level": {
                "levels": list(LEVEL_NAMES.values()),
                "unit_modes": list(ALL_CONFIG_UNIT_MODES),
                "similarity_metrics": list(ALL_CONFIG_BULLET_METRICS),
                "tweet_overlap": [label for label, _ in ALL_CONFIG_TWEET_OVERLAP],
            },
        },
        "configured_metrics": configured_metrics,
        "weighted_alignment": weighted_alignment,
    }
    payload["summary"] = build_all_config_summary(payload)
    return payload


def _metric_overall_summary(name: str, block: dict[str, Any]) -> dict[str, Any]:
    if block.get("mode") == "disabled":
        return {"mode": "disabled"}
    if block.get("error"):
        return {
            "mode": block.get("mode"),
            "status": block.get("status", "skipped"),
            "reason": block.get("reason"),
            "error": block["error"],
            "warnings": block.get("warnings", []),
        }
    overall = block.get("overall") or {}
    entry: dict[str, Any] = {
        "mode": block.get("mode"),
        "status": block.get("status", "scored"),
        "reason": block.get("reason"),
        "warnings": block.get("warnings", []),
        "aggregation": block.get("aggregation"),
        "n_scored": block.get("n_scored"),
        "n_skipped_both_empty": block.get("n_skipped_both_empty", 0),
    }
    if name == "rouge":
        for metric in ("rouge1", "rouge2", "rougeL"):
            entry[metric] = overall.get(metric)
    elif name == "bertscore":
        entry.update({
            "precision": overall.get("precision"),
            "recall": overall.get("recall"),
            "f1": overall.get("f1"),
        })
    else:
        entry["score"] = overall.get("score")
    aggregates = block.get("aggregates") or {}
    entry["macro"] = aggregates.get("macro")
    entry["micro"] = aggregates.get("micro")
    return entry


def build_flat_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a compact single-mode summary."""
    summary: dict[str, Any] = {}
    metrics = payload.get("configured_metrics") or {}

    for name in ("rouge", "bertscore", "bleurt"):
        block = metrics.get(name) or {}
        if block.get("mode") == "disabled":
            summary[name] = {"mode": "disabled"}
            continue
        summary[name] = _metric_overall_summary(name, block)

    weighted = payload.get("weighted_alignment") or {}
    if weighted.get("mode") == "disabled":
        summary["weighted_alignment"] = {"mode": "disabled"}
    else:
        wa_summary = weighted.get("summary") or {}
        scope = (weighted.get("configuration") or {}).get("scope")
        macro_prefix = f"macro_{scope}_soft" if scope else "macro_soft"
        summary["weighted_alignment"] = {
            "status": weighted.get("status", "scored"),
            "reason": weighted.get("reason"),
            "warnings": weighted.get("warnings", []),
            "scope": scope,
            "metric": weighted.get("metric"),
            "threshold": weighted.get("threshold"),
            "micro_soft_precision": wa_summary.get("micro_soft_precision"),
            "micro_soft_recall": wa_summary.get("micro_soft_recall"),
            "micro_soft_f1": wa_summary.get("micro_soft_f1"),
            "macro_soft_precision": wa_summary.get(f"{macro_prefix}_precision"),
            "macro_soft_recall": wa_summary.get(f"{macro_prefix}_recall"),
            "macro_soft_f1": wa_summary.get(f"{macro_prefix}_f1"),
            "structure_recall": wa_summary.get("structure_recall"),
            "structure_precision": wa_summary.get("structure_precision"),
            "matched_pairs": wa_summary.get("matched_pairs"),
            "gold_units": wa_summary.get("gold_units"),
            "system_units": wa_summary.get("system_units"),
            "warning_count": wa_summary.get("warning_count"),
        }
    return summary


def build_all_modes_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for name in ALL_MODE_METRICS:
        summary[name] = {
            level: _metric_overall_summary(name, (payload["configured_metrics"][name][level]))
            for level in LEVEL_NAMES.values()
        }

    weighted = payload.get("weighted_alignment") or {}
    if weighted.get("mode") == "disabled":
        summary["weighted_alignment"] = {"mode": "disabled"}
    else:
        summary["weighted_alignment"] = {}
        for level in LEVEL_NAMES.values():
            block = weighted[level]
            wa_summary = block.get("summary") or {}
            summary["weighted_alignment"][level] = {
                "status": block.get("status", "scored"),
                "reason": block.get("reason"),
                "error": block.get("error"),
                "warnings": block.get("warnings", []),
                "metric": block.get("metric"),
                "threshold": block.get("threshold"),
                "micro_soft_f1": wa_summary.get("micro_soft_f1"),
                "micro_soft_precision": wa_summary.get("micro_soft_precision"),
                "micro_soft_recall": wa_summary.get("micro_soft_recall"),
                "structure_recall": wa_summary.get("structure_recall"),
                "structure_precision": wa_summary.get("structure_precision"),
                "matched_pairs": wa_summary.get("matched_pairs"),
                "gold_units": wa_summary.get("gold_units"),
                "system_units": wa_summary.get("system_units"),
                "warning_count": wa_summary.get("warning_count"),
            }
    return summary


def _weighted_block_summary(block: dict[str, Any]) -> dict[str, Any]:
    tweet_overlap_config = (block.get("configuration") or {}).get("tweet_id_overlap") or {}
    tweet_overlap_enabled = tweet_overlap_config.get("enabled")
    tweet_overlap = (
        "on" if tweet_overlap_enabled else "off"
        if tweet_overlap_enabled is not None else block.get("tweet_overlap")
    )
    if block.get("error"):
        return {
            "status": block.get("status", "skipped"),
            "reason": block.get("reason"),
            "error": block["error"],
            "warnings": block.get("warnings", []),
            "tweet_overlap": tweet_overlap,
        }
    wa_summary = block.get("summary") or {}
    return {
        "status": block.get("status", "scored"),
        "reason": block.get("reason"),
        "warnings": block.get("warnings", []),
        "metric": block.get("metric"),
        "unit_mode": (block.get("configuration") or {}).get("unit_mode"),
        "tweet_overlap": tweet_overlap,
        "text_weight": tweet_overlap_config.get("text_weight"),
        "tweet_id_weight": tweet_overlap_config.get("tweet_id_weight"),
        "threshold": block.get("threshold"),
        "micro_soft_f1": wa_summary.get("micro_soft_f1"),
        "micro_soft_precision": wa_summary.get("micro_soft_precision"),
        "micro_soft_recall": wa_summary.get("micro_soft_recall"),
        "structure_recall": wa_summary.get("structure_recall"),
        "structure_precision": wa_summary.get("structure_precision"),
        "matched_pairs": wa_summary.get("matched_pairs"),
        "gold_units": wa_summary.get("gold_units"),
        "system_units": wa_summary.get("system_units"),
        "warning_count": wa_summary.get("warning_count"),
    }


def build_all_config_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"rows": []}

    for name in ALL_CONFIG_TEXT_METRICS:
        summary[name] = {
            level: _metric_overall_summary(
                name, (payload["configured_metrics"][name][level])
            )
            for level in LEVEL_NAMES.values()
        }
        for level in LEVEL_NAMES.values():
            summary["rows"].append({
                "path": "text_level",
                "metric": name,
                "level": level,
                **_metric_overall_summary(
                    name, payload["configured_metrics"][name][level]
                ),
            })

    weighted = payload.get("weighted_alignment") or {}
    if weighted.get("mode") == "disabled":
        summary["weighted_alignment"] = {"mode": "disabled"}
        return summary

    summary["weighted_alignment"] = {}
    for level in LEVEL_NAMES.values():
        summary["weighted_alignment"][level] = {}
        for unit_mode in ALL_CONFIG_UNIT_MODES:
            summary["weighted_alignment"][level][unit_mode] = {}
            for metric in ALL_CONFIG_BULLET_METRICS:
                summary["weighted_alignment"][level][unit_mode][metric] = {}
                for overlap_label, _ in ALL_CONFIG_TWEET_OVERLAP:
                    block = weighted[level][unit_mode][metric][overlap_label]
                    entry = _weighted_block_summary(block)
                    entry["tweet_overlap"] = overlap_label
                    summary["weighted_alignment"][level][unit_mode][metric][overlap_label] = entry
                    summary["rows"].append({
                        "path": "bullet_level",
                        "level": level,
                        "unit_mode": unit_mode,
                        "metric": metric,
                        "tweet_overlap": overlap_label,
                        **entry,
                    })
    return summary


def write_summary_csv(payload: dict[str, Any], csv_path: Path) -> None:
    view = payload.get("view")
    if view == "all_config":
        write_all_config_csv(payload, csv_path)
        return
    if view == "all_modes":
        write_all_modes_csv(payload, csv_path)
        return

    flat = payload.get("summary") or {}
    row: dict[str, Any] = {
        "gold": Path(payload["gold"]).name,
        "system": Path(payload["system"]).name,
    }
    row.update(_single_mode_csv_fields(flat))
    _write_csv_rows(csv_path, [row])


def write_all_modes_csv(payload: dict[str, Any], csv_path: Path) -> None:
    flat = payload.get("summary") or {}
    rows = []
    for level in LEVEL_NAMES.values():
        row: dict[str, Any] = {
            "level": level,
            "gold": Path(payload["gold"]).name,
            "system": Path(payload["system"]).name,
        }
        rouge = (flat.get("rouge") or {}).get(level) or {}
        row.update({
            "rouge_status": rouge.get("status"),
            "rouge_reason": rouge.get("reason"),
        })
        if rouge.get("mode") != "disabled" and not rouge.get("error"):
            row.update(_rouge_csv_fields(rouge, prefix="rouge_"))
            row.update(_text_aggregate_csv_fields("rouge", rouge))
        bert = (flat.get("bertscore") or {}).get(level) or {}
        row.update({
            "bertscore_status": bert.get("status"),
            "bertscore_reason": bert.get("reason"),
        })
        if bert.get("mode") != "disabled" and not bert.get("error"):
            row.update({
                "bertscore_n_scored": bert.get("n_scored"),
                "bertscore_precision": bert.get("precision"),
                "bertscore_recall": bert.get("recall"),
                "bertscore_f1": bert.get("f1"),
            })
            row.update(_text_aggregate_csv_fields("bertscore", bert))
        bleurt = (flat.get("bleurt") or {}).get(level) or {}
        row.update({
            "bleurt_status": bleurt.get("status"),
            "bleurt_reason": bleurt.get("reason"),
        })
        if bleurt.get("mode") != "disabled" and not bleurt.get("error"):
            row.update({
                "bleurt_n_scored": bleurt.get("n_scored"),
                "bleurt": bleurt.get("score"),
            })
            row.update(_text_aggregate_csv_fields("bleurt", bleurt))
        weighted = flat.get("weighted_alignment") or {}
        if weighted.get("mode") != "disabled":
            wa = weighted.get(level) or {}
            row.update({
                "weighted_status": wa.get("status"),
                "weighted_reason": wa.get("reason"),
                "weighted_metric": wa.get("metric"),
                "weighted_micro_soft_f1": wa.get("micro_soft_f1"),
                "weighted_micro_soft_precision": wa.get("micro_soft_precision"),
                "weighted_micro_soft_recall": wa.get("micro_soft_recall"),
                "weighted_structure_recall": wa.get("structure_recall"),
                "weighted_matched_pairs": wa.get("matched_pairs"),
            })
        rows.append(row)
    _write_csv_rows(csv_path, rows)


def write_all_config_csv(payload: dict[str, Any], csv_path: Path) -> None:
    flat = payload.get("summary") or {}
    rows: list[dict[str, Any]] = []
    for row in flat.get("rows") or []:
        csv_row: dict[str, Any] = {
            "path": row.get("path"),
            "metric": row.get("metric"),
            "level": row.get("level"),
            "gold": Path(payload["gold"]).name,
            "system": Path(payload["system"]).name,
            "error": row.get("error"),
            "status": row.get("status"),
            "reason": row.get("reason"),
        }
        if row.get("path") == "text_level":
            csv_row["mode"] = row.get("mode")
            csv_row["n_scored"] = row.get("n_scored")
            if row.get("mode") != "disabled" and not row.get("error"):
                name = row.get("metric", "")
                if name == "rouge":
                    csv_row.update(_rouge_csv_fields(row, prefix=""))
                elif name == "bertscore":
                    csv_row.update({
                        "precision": row.get("precision"),
                        "recall": row.get("recall"),
                        "f1": row.get("f1"),
                    })
                elif name == "bleurt":
                    csv_row["score"] = row.get("score")
                csv_row.update(_text_aggregate_csv_fields(str(name), row))
        else:
            csv_row.update({
                "unit_mode": row.get("unit_mode"),
                "tweet_overlap": row.get("tweet_overlap"),
                "text_weight": row.get("text_weight"),
                "tweet_id_weight": row.get("tweet_id_weight"),
                "micro_soft_f1": row.get("micro_soft_f1"),
                "micro_soft_precision": row.get("micro_soft_precision"),
                "micro_soft_recall": row.get("micro_soft_recall"),
                "structure_recall": row.get("structure_recall"),
                "structure_precision": row.get("structure_precision"),
                "matched_pairs": row.get("matched_pairs"),
                "gold_units": row.get("gold_units"),
                "system_units": row.get("system_units"),
                "warning_count": row.get("warning_count"),
            })
        rows.append(csv_row)
    _write_csv_rows(csv_path, rows)


def _single_mode_csv_fields(flat: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    rouge = flat.get("rouge") or {}
    if rouge.get("mode") != "disabled":
        row["rouge_mode"] = rouge.get("mode")
        row["rouge_status"] = rouge.get("status")
        row["rouge_reason"] = rouge.get("reason")
        row.update(_rouge_csv_fields(rouge, prefix=""))
        row.update(_text_aggregate_csv_fields("rouge", rouge))
    bert = flat.get("bertscore") or {}
    if bert.get("mode") != "disabled":
        row.update({
            "bertscore_status": bert.get("status"),
            "bertscore_reason": bert.get("reason"),
            "bertscore_mode": bert.get("mode"),
            "bertscore_n_scored": bert.get("n_scored"),
            "bertscore_precision": bert.get("precision"),
            "bertscore_recall": bert.get("recall"),
            "bertscore_f1": bert.get("f1"),
        })
        row.update(_text_aggregate_csv_fields("bertscore", bert))
    bleurt = flat.get("bleurt") or {}
    if bleurt.get("mode") != "disabled":
        row.update({
            "bleurt_status": bleurt.get("status"),
            "bleurt_reason": bleurt.get("reason"),
            "bleurt_mode": bleurt.get("mode"),
            "bleurt_n_scored": bleurt.get("n_scored"),
            "bleurt": bleurt.get("score"),
        })
        row.update(_text_aggregate_csv_fields("bleurt", bleurt))
    weighted = flat.get("weighted_alignment") or {}
    if weighted.get("mode") != "disabled":
        row.update({
            "weighted_status": weighted.get("status"),
            "weighted_reason": weighted.get("reason"),
            "weighted_scope": weighted.get("scope"),
            "weighted_metric": weighted.get("metric"),
            "weighted_threshold": weighted.get("threshold"),
            "weighted_micro_soft_f1": weighted.get("micro_soft_f1"),
            "weighted_micro_soft_precision": weighted.get("micro_soft_precision"),
            "weighted_micro_soft_recall": weighted.get("micro_soft_recall"),
            "weighted_structure_recall": weighted.get("structure_recall"),
            "weighted_structure_precision": weighted.get("structure_precision"),
            "weighted_matched_pairs": weighted.get("matched_pairs"),
            "weighted_warning_count": weighted.get("warning_count"),
        })
    return row


def _rouge_csv_fields(rouge: dict[str, Any], *, prefix: str) -> dict[str, Any]:
    row: dict[str, Any] = {f"{prefix}n_scored": rouge.get("n_scored")} if prefix else {
        "rouge_n_scored": rouge.get("n_scored"),
    }
    for metric in ("rouge1", "rouge2", "rougeL"):
        scores = rouge.get(metric) or {}
        short = metric.replace("rouge", "r").replace("L", "l")
        row[f"{prefix}{short}_p" if prefix else f"{short}_p"] = scores.get("precision")
        row[f"{prefix}{short}_r" if prefix else f"{short}_r"] = scores.get("recall")
        row[f"{prefix}{short}_f" if prefix else f"{short}_f"] = scores.get("fmeasure")
    return row


def _text_aggregate_csv_fields(name: str, block: dict[str, Any]) -> dict[str, Any]:
    """Flatten text-level aggregate fields."""
    row: dict[str, Any] = {
        f"{name}_aggregation": block.get("aggregation"),
        f"{name}_n_skipped_both_empty": block.get("n_skipped_both_empty", 0),
    }
    for aggregation in ("macro", "micro"):
        aggregate = block.get(aggregation) or {}
        if name == "rouge":
            for metric in ("rouge1", "rouge2", "rougeL"):
                scores = aggregate.get(metric) or {}
                short = metric.replace("rouge", "r").replace("L", "l")
                row[f"{name}_{aggregation}_{short}_p"] = scores.get("precision")
                row[f"{name}_{aggregation}_{short}_r"] = scores.get("recall")
                row[f"{name}_{aggregation}_{short}_f"] = scores.get("fmeasure")
        elif name == "bertscore":
            for flavour in ("precision", "recall", "f1"):
                row[f"{name}_{aggregation}_{flavour}"] = aggregate.get(flavour)
        elif name == "bleurt":
            row[f"{name}_{aggregation}_score"] = aggregate.get("score")
    return row


def _write_csv_rows(csv_path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Unified gold vs system evaluation (configured metrics + weighted alignment)."
    )
    parser.add_argument("--gold", type=Path, required=True, help="Gold SITREP JSON.")
    parser.add_argument("--system", type=Path, required=True, help="System SITREP JSON.")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_EVAL_CONFIG,
        help=f"Evaluation config (default: {DEFAULT_EVAL_CONFIG}).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write combined JSON here (default: print to stdout).",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Optional summary CSV (one row per combination when --all-config).",
    )
    parser.add_argument(
        "--all-modes",
        action="store_true",
        help=(
            "Run ROUGE/BERTScore/BLEURT and weighted alignment at document, "
            "section, and subsection levels."
        ),
    )
    parser.add_argument(
        "--all-config",
        action="store_true",
        help=(
            "Sweep all config combinations: text-level ROUGE/BERTScore/BLEURT at all "
            "levels, and bullet-level Hungarian alignment at all level × unit_mode × "
            "similarity_metric × tweet_overlap combinations."
        ),
    )
    parser.add_argument(
        "--sections",
        default=None,
        help="Comma-separated section IDs to evaluate, or 'all' (overrides config).",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Include per-group weighted-alignment detail (omit similarity matrices).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not print JSON to stdout when --out is set.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        evaluation_scope = resolve_evaluation_scope(args.config, args.sections)
    except ValueError as exc:
        raise SystemExit(f"invalid evaluation scope: {exc}") from exc
    result = evaluate_pair(
        args.gold,
        args.system,
        args.config,
        include_group_detail=args.full,
        all_modes=args.all_modes,
        all_config=args.all_config,
        evaluation_scope=evaluation_scope,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
        print(f"[eval_pair] wrote {args.out}")
    if args.csv:
        write_summary_csv(result, args.csv)
        print(f"[eval_pair] wrote {args.csv}")
    if not args.quiet or not args.out:
        print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
