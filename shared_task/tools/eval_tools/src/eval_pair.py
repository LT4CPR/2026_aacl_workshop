"""Evaluate and report metrics for one gold/system SITREP pair."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
        "subsection_alignment_method": block.get(
            "subsection_alignment_method"
        ),
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
            "subsection_alignment_method": (
                weighted.get("configuration") or {}
            ).get("subsection_alignment_method"),
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
                "subsection_alignment_method": (
                    block.get("configuration") or {}
                ).get("subsection_alignment_method"),
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
        "subsection_alignment_method": (
            block.get("configuration") or {}
        ).get("subsection_alignment_method"),
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
