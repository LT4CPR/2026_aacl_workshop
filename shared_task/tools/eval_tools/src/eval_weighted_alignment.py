"""Bullet-level Hungarian alignment for structured SITREP JSON."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

from runtime_env import apply_safe_hf_env, ensure_safe_hf_env_for_main

ensure_safe_hf_env_for_main(__name__)
apply_safe_hf_env()

EVAL_DIR = Path(__file__).resolve().parent
RELEASE_ROOT = EVAL_DIR.parent
DEFAULT_CONFIG = RELEASE_ROOT / "config" / "evaluation.yaml"
DEFAULT_MODEL = "microsoft/deberta-xlarge-mnli"
DEFAULT_MODELS = {
    "bertscore": DEFAULT_MODEL,
    "cosine": "sentence-transformers/all-mpnet-base-v2",
}
METRIC_ALIASES = {
    "bertscore": "bertscore",
    "rouge": "rougeL",
    "rougeL": "rougeL",
    "cosine": "cosine",
    "cosine-similarity": "cosine",
}

from eval_sitrep import _apply_bertscore_tokenizer_compat, resolve_bullet_level_spec
from evaluation_scope import EvaluationScope, resolve_evaluation_scope
from hungarian_alignment import align_weight_matrix_bipartite
from sitrep_units import (
    ExtractionResult,
    MODE_SCOPE,
    UnitExtractionError,
    extract_units_by_group,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Align System and Gold SITREP bullets with Hungarian matching."
    )
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--system", type=Path, action="append", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG,
        help="YAML containing metrics.bullet_level settings.",
    )
    parser.add_argument(
        "--metric", choices=("bertscore", "rougeL", "cosine"), default=None,
        help="Override similarity_metric from the YAML config.",
    )
    parser.add_argument(
        "--model", default=None,
        help="Override model_type for the selected metric (ignored for rougeL).",
    )
    parser.add_argument(
        "--batch-size", type=int, default=None,
        help="Override batch_size from the YAML config.",
    )
    parser.add_argument(
        "--threshold", type=float, default=None,
        help="Override alignment.threshold from the YAML config.",
    )
    parser.add_argument(
        "--sections",
        default=None,
        help=(
            "Comma-separated section IDs to evaluate, or 'all' for every "
            "available section (overrides config)."
        ),
    )
    parser.add_argument("--device", default=None)
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Replace an existing run's files only after the new run completes.",
    )
    return parser.parse_args()


def load_hungarian_config(
    path: Path, *, require_enabled: bool = True
) -> dict[str, Any]:
    """Load and validate bullet-level metric settings."""
    try:
        import yaml
    except ImportError as exc:
        raise SystemExit(
            "YAML configuration requires PyYAML; install requirements.txt"
        ) from exc

    if not path.is_file():
        raise SystemExit(f"Hungarian evaluation config not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    metrics = raw.get("metrics")
    if not isinstance(metrics, dict):
        raise SystemExit(f"Missing metrics mapping in config: {path}")
    spec = resolve_bullet_level_spec(metrics)
    if spec is None:
        raise SystemExit(
            f"Missing metrics.bullet_level in config: {path} "
            "(the compatibility key metrics.weighted_alignment is also accepted)"
        )

    mode = int(spec.get("mode", 3))
    if mode == 0:
        if require_enabled:
            raise SystemExit("bullet_level is disabled in the YAML config (mode: 0)")
        mode = 3
    if mode not in MODE_SCOPE:
        raise SystemExit(f"bullet_level.mode must be 1, 2, or 3; got {mode}")
    unit_mode = str(spec.get("unit_mode", spec.get("unit", "bullet")))
    if unit_mode not in {"bullet", "text"}:
        raise SystemExit(
            f"bullet_level.unit_mode must be text or bullet; got {unit_mode}"
        )
    scope = str(spec.get("scope", MODE_SCOPE[mode]))
    if scope != MODE_SCOPE[mode]:
        raise SystemExit(
            f"mode {mode} requires scope: {MODE_SCOPE[mode]}, got scope: {scope}"
        )

    aggregation = str(spec.get("aggregation", "micro"))
    if aggregation not in {"micro", "macro"}:
        raise SystemExit(f"Unsupported aggregation: {aggregation}")
    configured_metric = str(spec.get("similarity_metric", "bertscore"))
    if configured_metric not in METRIC_ALIASES:
        raise SystemExit(
            f"Unsupported similarity_metric: {configured_metric}; "
            "choose rougeL, bertscore, or cosine"
        )
    tweet_id_overlap_spec = spec.get("tweet_id_overlap") or {}
    if not isinstance(tweet_id_overlap_spec, dict):
        raise SystemExit("bullet_level.tweet_id_overlap must be a mapping")
    tweet_id_overlap_enabled = bool(tweet_id_overlap_spec.get("enabled", False))
    default_text_weight = 0.8 if tweet_id_overlap_enabled else 1.0
    text_weight = float(tweet_id_overlap_spec.get(
        "text_weight",
        tweet_id_overlap_spec.get(
            "lambda",
            tweet_id_overlap_spec.get("lambda_text", default_text_weight),
        ),
    ))
    if not np.isfinite(text_weight) or not 0.0 <= text_weight <= 1.0:
        raise SystemExit(
            "bullet_level.tweet_id_overlap.text_weight must be finite and in [0, 1]"
        )
    tweet_id_overlap = {
        "enabled": tweet_id_overlap_enabled,
        "metric": "jaccard",
        "text_weight": text_weight,
        "tweet_id_weight": 1.0 - text_weight if tweet_id_overlap_enabled else 0.0,
    }

    alignment = spec.get("alignment") or {}
    if alignment.get("method", "bipartite") != "bipartite":
        raise SystemExit("bullet_level.alignment.method must be bipartite")
    if alignment.get("algorithm", "hungarian") != "hungarian":
        raise SystemExit("bullet_level.alignment.algorithm must be hungarian")

    batch_size = int(spec.get("batch_size", 16))
    if batch_size <= 0:
        raise SystemExit("bullet_level.batch_size must be positive")
    threshold_spec = alignment.get("threshold", 0.0)
    if isinstance(threshold_spec, dict):
        thresholds = {}
        for raw_metric, raw_threshold in threshold_spec.items():
            if raw_metric not in METRIC_ALIASES:
                raise SystemExit(f"Unsupported threshold metric: {raw_metric}")
            thresholds[METRIC_ALIASES[raw_metric]] = float(raw_threshold)
        missing = sorted(set(METRIC_ALIASES.values()) - set(thresholds))
        if missing:
            raise SystemExit(
                "bullet_level.alignment.threshold is missing: "
                + ", ".join(missing)
            )
    else:
        threshold = float(threshold_spec)
        thresholds = {metric: threshold for metric in set(METRIC_ALIASES.values())}
    if any(not np.isfinite(value) or value < 0.0 for value in thresholds.values()):
        raise SystemExit(
            "bullet_level thresholds must be finite and non-negative"
        )

    model_spec = spec.get("model_type", DEFAULT_MODELS)
    if isinstance(model_spec, dict):
        models = {
            metric: str(model_spec.get(metric, default_model))
            for metric, default_model in DEFAULT_MODELS.items()
        }
    else:
        models = {metric: str(model_spec) for metric in DEFAULT_MODELS}

    on_missing_structure = str(spec.get("on_missing_structure", "warn"))
    if on_missing_structure not in {"warn", "fail"}:
        raise SystemExit(
            "bullet_level.on_missing_structure must be warn or fail; "
            f"got {on_missing_structure}"
        )

    return {
        "mode": mode,
        "unit_mode": unit_mode,
        "scope": scope,
        "aggregation": aggregation,
        "metric": METRIC_ALIASES[configured_metric],
        "models": models,
        "batch_size": batch_size,
        "thresholds": thresholds,
        "tweet_id_overlap": tweet_id_overlap,
        "alignment_method": "bipartite",
        "alignment_algorithm": "hungarian",
        "on_missing_structure": on_missing_structure,
    }


def load_units(
    path: Path,
    mode: int,
    unit_mode: str,
    selected_sections: tuple[str, ...] | None = None,
) -> ExtractionResult:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"Cannot read SITREP JSON: {path}: {exc}") from exc
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Failed to parse JSON: {path}: {exc}") from exc
    try:
        return extract_units_by_group(
            document,
            mode=mode,
            unit_mode=unit_mode,
            selected_sections=selected_sections,
        )
    except UnitExtractionError as exc:
        raise SystemExit(
            f"Unit extraction failed for {path} [{exc.code}]: {exc}"
        ) from exc


def build_evaluation_warnings(
    gold: dict,
    system: dict,
    gold_extraction: ExtractionResult,
    system_extraction: ExtractionResult,
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for side, extraction in (("gold", gold_extraction), ("system", system_extraction)):
        for warning in extraction.warnings:
            warnings.append({"side": side, **warning})

    gold_keys = set(gold)
    system_keys = set(system)
    gold_only = sorted(gold_keys - system_keys)
    system_only = sorted(system_keys - gold_keys)
    matched_keys = sorted(gold_keys & system_keys)

    total_gold = sum(len(units) for units in gold.values())
    total_system = sum(len(units) for units in system.values())

    if total_gold == 0:
        warnings.append({
            "side": "gold",
            "code": "empty_gold_units",
            "message": "gold extraction produced zero comparison units",
        })
    if total_system == 0:
        warnings.append({
            "side": "system",
            "code": "empty_system_units",
            "message": "system extraction produced zero comparison units",
        })
    if gold_only:
        warnings.append({
            "code": "gold_only_groups",
            "message": "gold has groups with no matching system group key",
            "count": len(gold_only),
            "groups": [f"{a}/{b}" for a, b in gold_only],
        })
    if system_only:
        warnings.append({
            "code": "system_only_groups",
            "message": "system has groups with no matching gold group key",
            "count": len(system_only),
            "groups": [f"{a}/{b}" for a, b in system_only],
        })
    if total_gold and total_system and not matched_keys:
        warnings.append({
            "code": "no_shared_groups",
            "message": "gold and system share no group keys; all matches will be empty",
        })
    elif matched_keys and (gold_only or system_only):
        warnings.append({
            "code": "partial_key_overlap",
            "message": "only some group keys overlap between gold and system",
            "shared_groups": len(matched_keys),
            "gold_only_groups": len(gold_only),
            "system_only_groups": len(system_only),
        })
    return warnings


def summarize_warnings(warnings: list[dict[str, Any]]) -> dict[str, Any]:
    codes = sorted({str(warning.get("code", "")) for warning in warnings if warning.get("code")})
    return {
        "warning_count": len(warnings),
        "warning_codes": ";".join(codes),
        "gold_only_groups": next(
            (warning.get("count", 0) for warning in warnings if warning.get("code") == "gold_only_groups"),
            0,
        ),
        "system_only_groups": next(
            (warning.get("count", 0) for warning in warnings if warning.get("code") == "system_only_groups"),
            0,
        ),
    }


def compute_structure_metrics(gold: dict, system: dict) -> dict[str, float]:
    gold_group_count = len(gold)
    system_group_count = len(system)
    shared_group_count = len(set(gold) & set(system))
    return {
        "gold_groups": gold_group_count,
        "system_groups": system_group_count,
        "shared_groups": shared_group_count,
        "structure_recall": (
            shared_group_count / gold_group_count if gold_group_count else 0.0
        ),
        "structure_precision": (
            shared_group_count / system_group_count if system_group_count else 0.0
        ),
    }


def enforce_missing_structure_policy(
    result: dict[str, Any],
    system_path: Path,
    on_missing_structure: str,
) -> None:
    if on_missing_structure != "fail":
        return
    for warning in result["warnings"]:
        if (
            warning.get("side") == "system"
            and warning.get("code") == "missing_section_structure"
        ):
            reason = warning.get("reason", "unknown")
            raise SystemExit(
                "Refusing to continue because the system SITREP is missing "
                f"section structure ({reason}). "
                f"system={system_path} on_missing_structure=fail"
            )


def rouge_l_scores(candidates: list[str], references: list[str], **_: object) -> list[float]:
    try:
        from rouge_score import rouge_scorer
    except ImportError as exc:
        raise SystemExit("rougeL requires rouge-score; install requirements.txt") from exc
    scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)
    return [
        float(scorer.score(ref, cand)["rougeL"].fmeasure)
        for cand, ref in zip(candidates, references)
    ]


def bert_scores(
    candidates: list[str], references: list[str], *, model: str,
    batch_size: int, device: str | None,
) -> list[float]:
    try:
        import importlib
        importlib.import_module("bert_score.utils")
    except ImportError as exc:
        raise SystemExit("BERTScore requires bert-score; install requirements.txt") from exc
    _apply_bertscore_tokenizer_compat()

    score_module = importlib.import_module("bert_score.score")
    kwargs: dict[str, object] = {
        "model_type": model,
        "batch_size": batch_size,
        "verbose": True,
        "rescale_with_baseline": False,
    }
    if device:
        kwargs["device"] = device
    _, _, f1 = score_module.score(candidates, references, **kwargs)
    return [float(value) for value in f1.cpu().tolist()]


def cosine_scores(
    candidates: list[str], references: list[str], *, model: str,
    batch_size: int, device: str | None,
) -> list[float]:
    """Compute cosine similarity for each candidate/reference pair."""
    try:
        import torch
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise SystemExit(
            "cosine requires sentence-transformers; install requirements.txt"
        ) from exc

    unique_texts = list(dict.fromkeys([*candidates, *references]))
    encoder_kwargs = {"device": device} if device else {}
    encoder = SentenceTransformer(model, **encoder_kwargs)
    embeddings = encoder.encode(
        unique_texts,
        batch_size=batch_size,
        convert_to_tensor=True,
        normalize_embeddings=True,
        show_progress_bar=True,
    ).cpu()
    index = {text: i for i, text in enumerate(unique_texts)}
    return [
        float(torch.dot(embeddings[index[cand]], embeddings[index[ref]]).clamp(0.0, 1.0))
        for cand, ref in zip(candidates, references)
    ]


def similarity_matrices(
    gold: dict, system: dict, score_fn: Callable[..., list[float]], **score_kwargs: object,
) -> dict:
    matrices = {}
    flat_candidates: list[str] = []
    flat_references: list[str] = []
    slices = []
    for key in sorted(set(gold) | set(system)):
        gold_units = gold.get(key, [])
        system_units = system.get(key, [])
        start = len(flat_candidates)
        for gold_unit in gold_units:
            for system_unit in system_units:
                flat_candidates.append(system_unit["text"])
                flat_references.append(gold_unit["text"])
        slices.append((key, len(gold_units), len(system_units), start, len(flat_candidates)))

    scores = score_fn(flat_candidates, flat_references, **score_kwargs) if flat_candidates else []
    for key, n_gold, n_system, start, end in slices:
        matrices[key] = np.asarray(scores[start:end], dtype=float).reshape(n_gold, n_system)
    return matrices


def normalize_tweet_ids(raw_ids: object) -> set[str]:
    """Normalize tweet IDs before Jaccard comparison."""
    if raw_ids is None:
        return set()
    if isinstance(raw_ids, (str, int, float)):
        values = [raw_ids]
    else:
        try:
            values = list(raw_ids)  # type: ignore[arg-type]
        except TypeError:
            values = [raw_ids]
    return {
        str(tweet_id).strip()
        for tweet_id in values
        if str(tweet_id).strip()
    }


def tweet_id_jaccard_similarity(gold_ids: object, system_ids: object) -> float:
    gold_set = normalize_tweet_ids(gold_ids)
    system_set = normalize_tweet_ids(system_ids)
    union = gold_set | system_set
    if not union:
        return 0.0
    return len(gold_set & system_set) / len(union)


def tweet_id_similarity_matrices(gold: dict, system: dict) -> dict:
    matrices = {}
    for key in sorted(set(gold) | set(system)):
        gold_units = gold.get(key, [])
        system_units = system.get(key, [])
        matrix = np.zeros((len(gold_units), len(system_units)), dtype=float)
        for gi, gold_unit in enumerate(gold_units):
            for si, system_unit in enumerate(system_units):
                matrix[gi, si] = tweet_id_jaccard_similarity(
                    gold_unit.get("tweet_ids"),
                    system_unit.get("tweet_ids"),
                )
        matrices[key] = matrix
    return matrices


def combine_similarity_matrices(
    text_matrices: dict,
    tweet_id_matrices: dict | None,
    *,
    text_weight: float,
) -> dict:
    if tweet_id_matrices is None:
        return text_matrices
    tweet_id_weight = 1.0 - text_weight
    return {
        key: text_weight * text_matrix + tweet_id_weight * tweet_id_matrices[key]
        for key, text_matrix in text_matrices.items()
    }


def safe_f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def evaluate_one(
    gold_path: Path, system_path: Path, metric: str, threshold: float,
    score_fn: Callable[..., list[float]], score_kwargs: dict[str, object],
    mode: int = 3, unit_mode: str = "bullet",
    effective_config: Optional[dict[str, Any]] = None,
    tweet_id_overlap: Optional[dict[str, Any]] = None,
    selected_sections: tuple[str, ...] | None = None,
) -> dict:
    gold_extraction = load_units(
        gold_path, mode=mode, unit_mode=unit_mode,
        selected_sections=selected_sections,
    )
    system_extraction = load_units(
        system_path, mode=mode, unit_mode=unit_mode,
        selected_sections=selected_sections,
    )
    gold = gold_extraction.units
    system = system_extraction.units
    warnings = build_evaluation_warnings(
        gold, system, gold_extraction, system_extraction,
    )
    warning_summary = summarize_warnings(warnings)
    structure_summary = compute_structure_metrics(gold, system)
    group_results = []
    total_weight = 0.0
    total_matches = 0
    total_gold_units = sum(len(units) for units in gold.values())
    total_system_units = sum(len(units) for units in system.values())

    def source_bullet_count(groups: dict) -> int:
        return sum(
            int(unit.get("source_bullet_count", 1))
            for units in groups.values()
            for unit in units
        )

    scope = MODE_SCOPE[mode]

    unavailable = [
        warning for warning in warnings
        if warning.get("code") == "missing_section_structure"
    ]
    if unavailable:
        sides = sorted({str(warning.get("side", "input")) for warning in unavailable})
        return {
            "gold": str(gold_path),
            "system": str(system_path),
            "metric": metric,
            "threshold": threshold,
            "configuration": effective_config or {},
            "status": "skipped",
            "reason": f"missing_{scope}_structure",
            "warnings": warnings,
            "summary": {
                "gold_units": total_gold_units,
                "system_units": total_system_units,
                "gold_source_bullets": source_bullet_count(gold),
                "system_source_bullets": source_bullet_count(system),
                "matched_pairs": None,
                "compared_groups": None,
                "groups_with_accepted_pairs": None,
                "unmatched_gold": None,
                "unmatched_system": None,
                "mean_positive_edge_weight": None,
                "micro_soft_precision": None,
                "micro_soft_recall": None,
                "micro_soft_f1": None,
                f"macro_{scope}_soft_precision": None,
                f"macro_{scope}_soft_recall": None,
                f"macro_{scope}_soft_f1": None,
                "unavailable_sides": sides,
                **structure_summary,
                **warning_summary,
            },
            "groups": [],
        }

    overlap_config = tweet_id_overlap or {}
    use_tweet_id_overlap = bool(overlap_config.get("enabled", False))
    text_weight = float(overlap_config.get("text_weight", 1.0))
    text_matrices = similarity_matrices(gold, system, score_fn, **score_kwargs)
    tweet_id_matrices = (
        tweet_id_similarity_matrices(gold, system)
        if use_tweet_id_overlap else None
    )
    matrices = combine_similarity_matrices(
        text_matrices,
        tweet_id_matrices,
        text_weight=text_weight,
    )

    for key in sorted(set(gold) | set(system)):
        gold_units = gold.get(key, [])
        system_units = system.get(key, [])
        matrix = matrices[key]
        aligned = align_weight_matrix_bipartite(matrix, threshold=threshold)
        pairs = []
        for pair in aligned.aligned_pairs:
            gi, si = pair["gold_index"], pair["system_index"]
            pairs.append({
                **pair,
                "gold_bullet_id": gold_units[gi].get("bullet_id"),
                "system_bullet_id": system_units[si].get("bullet_id"),
                "text_similarity": float(text_matrices[key][gi, si]),
                "tweet_id_similarity": (
                    float(tweet_id_matrices[key][gi, si])
                    if tweet_id_matrices is not None else None
                ),
                "gold_tweet_ids": sorted(normalize_tweet_ids(
                    gold_units[gi].get("tweet_ids")
                )),
                "system_tweet_ids": sorted(normalize_tweet_ids(
                    system_units[si].get("tweet_ids")
                )),
                "gold_text": gold_units[gi]["text"],
                "system_text": system_units[si]["text"],
            })
        weight = aligned.total_weight
        soft_precision = weight / len(system_units) if system_units else 0.0
        soft_recall = weight / len(gold_units) if gold_units else 0.0
        group_id = "document" if mode == 1 else key[0] if mode == 2 else f"{key[0]}/{key[1]}"
        group_results.append({
            "scope": scope,
            "group_id": group_id,
            "section_id": key[0] if mode >= 2 else None,
            "subsection_id": key[1] if mode == 3 else None,
            "gold_count": len(gold_units),
            "system_count": len(system_units),
            "matched_count": len(pairs),
            "mean_positive_edge_weight": weight / len(pairs) if pairs else 0.0,
            "soft_precision": soft_precision,
            "soft_recall": soft_recall,
            "soft_f1": safe_f1(soft_precision, soft_recall),
            "total_weight": weight,
            "pairs": pairs,
            "unmatched_gold": [gold_units[i] for i in aligned.unmatched_gold],
            "unmatched_system": [system_units[i] for i in aligned.unmatched_system],
            "similarity_matrix": matrix.tolist(),
            "text_similarity_matrix": (
                text_matrices[key].tolist() if use_tweet_id_overlap else None
            ),
            "tweet_id_similarity_matrix": (
                tweet_id_matrices[key].tolist()
                if tweet_id_matrices is not None else None
            ),
        })
        total_weight += weight
        total_matches += len(pairs)

    micro_soft_precision = (
        total_weight / total_system_units if total_system_units else 0.0
    )
    micro_soft_recall = total_weight / total_gold_units if total_gold_units else 0.0
    nonempty = [
        row for row in group_results if row["gold_count"] or row["system_count"]
    ]
    macro_soft_precision = (
        sum(row["soft_precision"] for row in nonempty) / len(nonempty)
        if nonempty else 0.0
    )
    macro_soft_recall = (
        sum(row["soft_recall"] for row in nonempty) / len(nonempty)
        if nonempty else 0.0
    )
    macro_soft_f1 = (
        sum(row["soft_f1"] for row in nonempty) / len(nonempty)
        if nonempty else 0.0
    )
    macro_prefix = f"macro_{scope}_soft"
    compared_group_count = sum(
        1 for row in group_results if row["gold_count"] and row["system_count"]
    )
    accepted_pair_group_count = sum(
        1 for row in group_results if row["matched_count"] > 0
    )
    return {
        "gold": str(gold_path),
        "system": str(system_path),
        "metric": metric,
        "threshold": threshold,
        "configuration": effective_config or {},
        "status": "scored",
        "warnings": warnings,
        "summary": {
            "gold_units": total_gold_units,
            "system_units": total_system_units,
            "gold_source_bullets": source_bullet_count(gold),
            "system_source_bullets": source_bullet_count(system),
            "matched_pairs": total_matches,
            "compared_groups": compared_group_count,
            "groups_with_accepted_pairs": accepted_pair_group_count,
            "unmatched_gold": total_gold_units - total_matches,
            "unmatched_system": total_system_units - total_matches,
            "mean_positive_edge_weight": (
                total_weight / total_matches if total_matches else 0.0
            ),
            "micro_soft_precision": micro_soft_precision,
            "micro_soft_recall": micro_soft_recall,
            "micro_soft_f1": safe_f1(micro_soft_precision, micro_soft_recall),
            f"{macro_prefix}_precision": macro_soft_precision,
            f"{macro_prefix}_recall": macro_soft_recall,
            f"{macro_prefix}_f1": macro_soft_f1,
            **structure_summary,
            **warning_summary,
        },
        "groups": group_results,
    }


def write_outputs(result: dict, out_dir: Path) -> None:
    stem = Path(result["system"]).stem
    json_path = out_dir / f"{stem}__hungarian.json"
    pairs_path = out_dir / f"{stem}__pairs.csv"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    with pairs_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow([
            "scope", "group_id", "section_id", "subsection_id",
            "gold_index", "system_index", "weight", "gold_bullet_id",
            "system_bullet_id", "text_similarity", "tweet_id_similarity",
            "gold_tweet_ids", "system_tweet_ids", "gold_text", "system_text",
        ])
        for group in result["groups"]:
            for pair in group["pairs"]:
                writer.writerow([
                    group["scope"], group["group_id"],
                    group["section_id"], group["subsection_id"],
                    pair["gold_index"], pair["system_index"], pair["weight"],
                    pair["gold_bullet_id"], pair["system_bullet_id"],
                    pair.get("text_similarity"), pair.get("tweet_id_similarity"),
                    ";".join(pair.get("gold_tweet_ids") or []),
                    ";".join(pair.get("system_tweet_ids") or []),
                    pair["gold_text"], pair["system_text"],
                ])
    return None


def write_summary(results: list[dict], output_path: Path) -> None:
    summary_fields = list(results[0]["summary"].keys()) if results else []
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["system", "metric", "threshold", *summary_fields],
            lineterminator="\n",
        )
        writer.writeheader()
        for result in results:
            writer.writerow({
                "system": Path(result["system"]).name,
                "metric": result["metric"],
                "threshold": result["threshold"],
                **result["summary"],
            })


def planned_output_names(system_paths: list[Path]) -> list[str]:
    names = ["summary.csv", "manifest.json"]
    for system_path in system_paths:
        names.extend([
            f"{system_path.stem}__hungarian.json",
            f"{system_path.stem}__pairs.csv",
        ])
    return names


def publish_staged_run(
    staging_dir: Path,
    out_dir: Path,
    output_names: list[str],
    overwrite: bool,
) -> None:
    existing = [out_dir / name for name in output_names if (out_dir / name).exists()]
    if existing and not overwrite:
        preview = "\n  ".join(str(path) for path in existing[:5])
        raise SystemExit(
            "Refusing to overwrite existing evaluation output. "
            "Choose a new --out-dir or pass --overwrite:\n  " + preview
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in output_names:
        os.replace(staging_dir / name, out_dir / name)


def weighted_alignment_enabled(config_path: Path) -> bool:
    try:
        yaml = importlib.import_module("yaml")
    except ImportError:
        return False
    if not config_path.exists():
        return False
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    metrics = raw.get("metrics") or {}
    spec = resolve_bullet_level_spec(metrics)
    if not spec:
        return False
    try:
        return int(spec.get("mode", 0)) != 0
    except (TypeError, ValueError):
        return False


def resolve_weighted_run_options(
    config_path: Path,
    *,
    metric: str | None = None,
    model: str | None = None,
    batch_size: int | None = None,
    threshold: float | None = None,
    device: str | None = None,
    require_enabled: bool = True,
) -> tuple[
    dict[str, Any],
    str,
    float,
    Callable[..., list[float]],
    dict[str, object],
    dict[str, Any],
]:
    configured = load_hungarian_config(
        config_path, require_enabled=require_enabled
    )
    selected_metric = metric if metric is not None else configured["metric"]
    selected_model = (
        model
        if model is not None
        else configured["models"].get(selected_metric, DEFAULT_MODEL)
    )
    selected_batch_size = (
        batch_size if batch_size is not None else configured["batch_size"]
    )
    selected_threshold = (
        threshold
        if threshold is not None
        else configured["thresholds"][selected_metric]
    )
    if selected_batch_size <= 0:
        raise SystemExit("--batch-size must be positive")
    if not np.isfinite(selected_threshold) or selected_threshold < 0.0:
        raise SystemExit("--threshold must be finite and non-negative")

    effective_config = {
        **configured,
        "config_path": str(config_path),
        "metric": selected_metric,
        "model": selected_model,
        "batch_size": selected_batch_size,
        "threshold": selected_threshold,
    }
    if device is not None:
        effective_config["device"] = device
    score_fn = {
        "bertscore": bert_scores,
        "rougeL": rouge_l_scores,
        "cosine": cosine_scores,
    }[selected_metric]
    score_kwargs: dict[str, object] = {
        "model": selected_model,
        "batch_size": selected_batch_size,
        "device": device,
    }
    return (
        configured,
        selected_metric,
        selected_threshold,
        score_fn,
        score_kwargs,
        effective_config,
    )


def evaluate_weighted_alignment_pair(
    gold_path: Path,
    system_path: Path,
    config_path: Path,
    *,
    metric: str | None = None,
    model: str | None = None,
    batch_size: int | None = None,
    threshold: float | None = None,
    device: str | None = None,
    enforce_structure: bool = True,
    alignment_mode: int | None = None,
    unit_mode: str | None = None,
    tweet_id_overlap_enabled: bool | None = None,
    evaluation_scope: EvaluationScope | None = None,
) -> dict[str, Any]:
    sweep_override = (
        alignment_mode is not None
        or unit_mode is not None
        or metric is not None
        or tweet_id_overlap_enabled is not None
    )
    (
        configured,
        selected_metric,
        selected_threshold,
        score_fn,
        score_kwargs,
        effective_config,
    ) = resolve_weighted_run_options(
        config_path,
        metric=metric,
        model=model,
        batch_size=batch_size,
        threshold=threshold,
        device=device,
        require_enabled=not sweep_override,
    )
    if alignment_mode is not None:
        if alignment_mode not in MODE_SCOPE:
            raise SystemExit(f"alignment_mode must be 1, 2, or 3; got {alignment_mode}")
        configured = {
            **configured,
            "mode": alignment_mode,
            "scope": MODE_SCOPE[alignment_mode],
        }
        effective_config = {
            **effective_config,
            "mode": alignment_mode,
            "scope": MODE_SCOPE[alignment_mode],
        }
    if unit_mode is not None:
        if unit_mode not in {"bullet", "text"}:
            raise SystemExit(f"unit_mode must be bullet or text; got {unit_mode}")
        configured = {**configured, "unit_mode": unit_mode}
        effective_config = {**effective_config, "unit_mode": unit_mode}
    if tweet_id_overlap_enabled is not None:
        current_overlap = dict(configured.get("tweet_id_overlap") or {})
        current_overlap["enabled"] = bool(tweet_id_overlap_enabled)
        if not tweet_id_overlap_enabled:
            current_overlap["tweet_id_weight"] = 0.0
        else:
            current_overlap["tweet_id_weight"] = 1.0 - float(
                current_overlap.get("text_weight", 1.0)
            )
        configured = {**configured, "tweet_id_overlap": current_overlap}
        effective_config = {**effective_config, "tweet_id_overlap": current_overlap}
    scope = evaluation_scope or resolve_evaluation_scope(config_path)
    effective_config = {
        **effective_config,
        "evaluation_scope": scope.as_dict(),
    }
    result = evaluate_one(
        gold_path,
        system_path,
        selected_metric,
        selected_threshold,
        score_fn,
        score_kwargs,
        mode=configured["mode"],
        unit_mode=configured["unit_mode"],
        effective_config=effective_config,
        tweet_id_overlap=configured["tweet_id_overlap"],
        selected_sections=scope.section_ids,
    )
    if enforce_structure:
        enforce_missing_structure_policy(
            result,
            system_path,
            configured["on_missing_structure"],
        )
    return result


def slim_weighted_alignment_result(
    result: dict[str, Any], *, include_groups: bool = False
) -> dict[str, Any]:
    """Return alignment output without large matrices."""
    slim = {
        key: result[key]
        for key in (
            "gold",
            "system",
            "metric",
            "threshold",
            "configuration",
            "status",
            "reason",
            "warnings",
            "summary",
        )
        if key in result
    }
    if include_groups:
        slim["groups"] = [
            {
                key: value
                for key, value in group.items()
                if not key.endswith("_matrix") and key != "similarity_matrix"
            }
            for group in result.get("groups", [])
        ]
    return slim


def main() -> None:
    args = parse_args()
    try:
        evaluation_scope = resolve_evaluation_scope(args.config, args.sections)
    except ValueError as exc:
        raise SystemExit(f"invalid evaluation scope: {exc}") from exc
    (
        configured,
        metric,
        threshold,
        score_fn,
        score_kwargs,
        effective_config,
    ) = resolve_weighted_run_options(
        args.config,
        metric=args.metric,
        model=args.model,
        batch_size=args.batch_size,
        threshold=args.threshold,
        device=args.device,
    )
    effective_config = {
        **effective_config,
        "evaluation_scope": evaluation_scope.as_dict(),
    }
    print(
        "[hungarian] "
        f"config={args.config} metric={metric} aggregation={configured['aggregation']} "
        f"threshold={threshold:g}"
    )
    output_names = planned_output_names(args.system)
    args.out_dir.parent.mkdir(parents=True, exist_ok=True)
    existing = [
        args.out_dir / name for name in output_names
        if (args.out_dir / name).exists()
    ]
    if existing and not args.overwrite:
        preview = "\n  ".join(str(path) for path in existing[:5])
        raise SystemExit(
            "Refusing to overwrite existing evaluation output. "
            "Choose a new --out-dir or pass --overwrite:\n  " + preview
        )

    with tempfile.TemporaryDirectory(
        prefix=".hungarian-staging-", dir=args.out_dir.parent
    ) as temporary:
        staging_dir = Path(temporary)
        results = []
        for system_path in args.system:
            result = evaluate_one(
                args.gold, system_path, metric, threshold, score_fn, score_kwargs,
                mode=configured["mode"], unit_mode=configured["unit_mode"],
                effective_config=effective_config,
                tweet_id_overlap=configured["tweet_id_overlap"],
                selected_sections=evaluation_scope.section_ids,
            )
            enforce_missing_structure_policy(
                result,
                system_path,
                configured["on_missing_structure"],
            )
            write_outputs(result, staging_dir)
            results.append(result)
            if result["warnings"]:
                joined = ", ".join(
                    f"{warning.get('code')}({warning.get('side', 'both')})"
                    for warning in result["warnings"]
                )
                print(f"[hungarian] warnings for {system_path.name}: {joined}")

        write_summary(results, staging_dir / "summary.csv")
        manifest = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "config_path": str(args.config),
            "config_sha256": hashlib.sha256(args.config.read_bytes()).hexdigest(),
            "gold": str(args.gold),
            "systems": [str(path) for path in args.system],
            "effective_config": effective_config,
            "evaluation_scope": evaluation_scope.as_dict(),
            "files": output_names,
            "warnings": [
                {
                    "system": Path(result["system"]).name,
                    "items": result["warnings"],
                }
                for result in results
            ],
        }
        (staging_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        publish_staged_run(
            staging_dir, args.out_dir, output_names, overwrite=args.overwrite
        )

    for name in output_names:
        print(f"wrote {args.out_dir / name}")


if __name__ == "__main__":
    main()
