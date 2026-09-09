from __future__ import annotations

import json
import sys
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from run_eval import (  # noqa: E402
    build_combined_log,
    build_combined_payload,
    discover_pairs,
    parse_cell_coordinates,
    parse_report_filename,
    write_system_outputs,
)
from reporting_config import load_reporting_config  # noqa: E402


def scored_item(instance_id: str, system_id: str, value: float) -> dict:
    crisis_id, cell_id = instance_id.split("/", 1)
    rouge_values = {
        "rouge1": {"precision": value, "recall": value, "fmeasure": value},
        "rouge2": {"precision": value, "recall": value, "fmeasure": value},
        "rougeL": {"precision": value, "recall": value, "fmeasure": value},
    }
    return {
        "instance_id": instance_id,
        "crisis_id": crisis_id,
        "cell_id": cell_id,
        "sys_id": system_id,
        "gold_file": f"data/gold-output/{crisis_id}/{cell_id}.report.json",
        "system_file": (
            f"data/sysId-output/{system_id}/{crisis_id}/{cell_id}.report.json"
        ),
        "status": "scored",
        "summary": {
            "rouge": {"micro": rouge_values, "macro": rouge_values},
            "bertscore": {
                "micro": {"precision": value, "recall": value, "f1": value},
                "macro": {"precision": value, "recall": value, "f1": value},
            },
            "bleurt": {
                "micro": {"score": value},
                "macro": {"score": value},
            },
            "weighted_alignment": {
                "scope": "subsection",
                "metric": "rougeL",
                "micro_soft_precision": value,
                "micro_soft_recall": value,
                "micro_soft_f1": value,
                "macro_soft_precision": value,
                "macro_soft_recall": value,
                "macro_soft_f1": value,
            },
        },
    }


def run_payload(results: list[dict], system_id: str = "UW-sys1") -> dict:
    return {
        "generated_at_utc": "2026-01-01T00:00:00+00:00",
        "config": "config/evaluation.yaml",
        "gold_dir": "data/gold-output",
        "system_dir": f"data/sysId-output/{system_id}",
        "system_id": system_id,
        "aggregation": {
            "within_document": "micro",
            "across_documents": "macro",
            "across_systems": "none",
        },
        "primary_score_config": {
            "enabled": True,
            "method": "mean_bertscore_f1_bleurt",
        },
        "results": results,
    }


def test_parse_report_filename_strips_report_suffix() -> None:
    assert parse_report_filename(Path("earthquake.W2.k3.report.json")) == (
        "earthquake.W2.k3"
    )


def test_parse_cell_coordinates_extracts_window_and_replicate() -> None:
    assert parse_cell_coordinates("earthquake", "earthquake.W2.k3") == (
        "W2",
        "k3",
    )


def test_parse_cell_coordinates_requires_matching_crisis_prefix() -> None:
    try:
        parse_cell_coordinates("flood", "earthquake.W2.k3")
    except ValueError as exc:
        assert "prefix must match" in str(exc)
    else:
        raise AssertionError("mismatched crisis prefix was accepted")


def test_discover_pairs_rejects_legacy_json_filenames(tmp_path: Path) -> None:
    gold_dir = tmp_path / "gold-output"
    system_dir = tmp_path / "UW-sys1"
    gold_dir.mkdir()
    system_dir.mkdir()
    (gold_dir / "earthquake-gold.json").write_text("{}\n", encoding="utf-8")

    try:
        discover_pairs(system_dir, gold_dir)
    except ValueError as exc:
        assert "every evaluation input must end with .report.json" in str(exc)
    else:
        raise AssertionError("legacy role-specific filename was accepted")


def test_discover_pairs_matches_crisis_and_cell_and_preserves_missing_sides(
    tmp_path: Path,
) -> None:
    gold_dir = tmp_path / "gold-output"
    system_dir = tmp_path / "UW-sys1"
    for root in (gold_dir, system_dir):
        (root / "earthquake").mkdir(parents=True)
        (root / "flood").mkdir(parents=True)
    for cell in ("earthquake.W1.k1", "earthquake.W1.k2"):
        (gold_dir / "earthquake" / f"{cell}.report.json").write_text(
            "{}\n", encoding="utf-8"
        )
    for crisis, cell in (
        ("earthquake", "earthquake.W1.k1"),
        ("flood", "flood.W1.k1"),
    ):
        (system_dir / crisis / f"{cell}.report.json").write_text(
            "{}\n", encoding="utf-8"
        )

    pairs = discover_pairs(system_dir, gold_dir)

    assert [pair["instance_id"] for pair in pairs] == [
        "earthquake/earthquake.W1.k1",
        "earthquake/earthquake.W1.k2",
        "flood/flood.W1.k1",
    ]
    assert pairs[0]["gold_path"].name == "earthquake.W1.k1.report.json"
    assert pairs[0]["system_path"].name == "earthquake.W1.k1.report.json"
    assert pairs[1]["gold_path"].name == "earthquake.W1.k2.report.json"
    assert pairs[1]["system_path"] is None
    assert pairs[2]["gold_path"] is None
    assert pairs[2]["system_path"].name == "flood.W1.k1.report.json"


def test_discover_pairs_rejects_extra_directory_layer(tmp_path: Path) -> None:
    gold_dir = tmp_path / "gold-output"
    system_dir = tmp_path / "UW-sys1"
    (gold_dir / "test" / "earthquake").mkdir(parents=True)
    system_dir.mkdir()
    (gold_dir / "test" / "earthquake" / "earthquake.W1.k1.report.json").write_text(
        "{}\n", encoding="utf-8"
    )

    try:
        discover_pairs(system_dir, gold_dir)
    except ValueError as exc:
        assert "direct children of one crisis directory" in str(exc)
    else:
        raise AssertionError("extra test directory layer was accepted")


def test_combined_payload_gives_crisis_documents_equal_weight() -> None:
    payload = run_payload([
        scored_item("earthquake/earthquake.W1.k1", "UW-sys1", 0.3),
        scored_item("earthquake/earthquake.W1.k2", "UW-sys1", 0.5),
        scored_item("flood/flood.W1.k1", "UW-sys1", 0.7),
    ])

    combined = build_combined_payload(payload)

    assert combined["system_id"] == "UW-sys1"
    assert combined["instance_count"] == 3
    assert combined["scored_instance_count"] == 3
    assert combined["crisis_count"] == 2
    assert combined["crisis_ids"] == ["earthquake", "flood"]
    assert combined["instance_ids"] == [
        "earthquake/earthquake.W1.k1",
        "earthquake/earthquake.W1.k2",
        "flood/flood.W1.k1",
    ]
    assert combined["coverage_ratio"] == 1.0
    assert combined["aggregation"] == {
        "level": "across_documents",
        "method": "macro",
        "hierarchy": [
            "replicates_within_window",
            "windows_within_document",
            "documents",
        ],
        "note": (
            "Replicates are averaged within each window, windows are averaged "
            "within each crisis/document, and crisis/documents receive equal "
            "weight in the overall result."
        ),
    }
    overall_macro = combined["overall_macro"]
    assert overall_macro["rouge1"]["fmeasure"] == 0.55
    assert overall_macro["weighted_alignment"]["f1"] == 0.55
    assert list(overall_macro["rouge1"]) == ["precision", "recall", "fmeasure"]
    assert list(overall_macro["bertscore"]) == ["precision", "recall", "f1"]
    assert list(overall_macro["weighted_alignment"])[:3] == [
        "precision",
        "recall",
        "f1",
    ]
    assert "bullet_alignment" not in overall_macro
    assert combined["primary_score"] == {
        "method": "mean_bertscore_f1_bleurt",
        "components": {"bertscore_f1": 0.55, "bleurt": 0.55},
        "score": 0.55,
    }
    assert "disasters" not in combined
    assert "macro_average" not in combined
    log = build_combined_log(combined)
    assert "Combined Multi-instance Evaluation Log" in log
    assert "3/3 scored instances" in log
    assert "Crisis count    : 2" in log
    assert "Crisis IDs      : earthquake, flood" in log
    assert "Overall Macro Results" in log
    assert "BERTScore F1" in log
    assert "level : across_documents" in log
    assert "method: macro" in log
    assert (
        "stages: replicates_within_window -> windows_within_document -> documents"
        in log
    )
    assert "Per-disaster Summary" not in log
    assert "Diagnostic" not in log
    assert "0.5500" in log
    assert "Primary Score" in log
    assert "mean_bertscore_f1_bleurt" in log
    assert "BERTScore F1    : 0.550000" in log
    assert "BLEURT          : 0.550000" in log
    assert "Score           : 0.550000" in log


def test_combined_payload_averages_replicates_then_windows_then_documents() -> None:
    combined = build_combined_payload(run_payload([
        scored_item("earthquake/earthquake.W1.k1", "UW-sys1", 0.0),
        scored_item("earthquake/earthquake.W1.k2", "UW-sys1", 1.0),
        scored_item("earthquake/earthquake.W2.k1", "UW-sys1", 1.0),
        scored_item("flood/flood.W1.k1", "UW-sys1", 0.0),
    ]))

    # Earthquake: ((0 + 1) / 2 + 1) / 2 = 0.75.
    # Flood: 0.0. Equal document weighting: (0.75 + 0.0) / 2 = 0.375.
    assert combined["overall_macro"]["bertscore"]["f1"] == 0.375
    assert combined["overall_macro"]["weighted_alignment"]["f1"] == 0.375
    assert combined["primary_score"]["score"] == 0.375


def test_combined_payload_reports_missing_system_instance() -> None:
    missing = {
        "instance_id": "earthquake/earthquake.W1.k2",
        "crisis_id": "earthquake",
        "cell_id": "earthquake.W1.k2",
        "sys_id": "UW-sys1",
        "gold_file": "data/gold-output/earthquake/earthquake.W1.k2.report.json",
        "system_file": None,
        "status": "missing_system",
        "error": "missing system file for instance: earthquake/earthquake.W1.k2",
    }
    combined = build_combined_payload(run_payload([
        scored_item("earthquake/earthquake.W1.k1", "UW-sys1", 0.4),
        missing,
    ]))

    assert combined["scored_instance_count"] == 1
    assert combined["instance_ids"] == [
        "earthquake/earthquake.W1.k1",
        "earthquake/earthquake.W1.k2",
    ]
    assert combined["coverage_ratio"] == 0.5
    assert combined["failed_instances"][0]["instance_id"] == (
        "earthquake/earthquake.W1.k2"
    )
    assert "missing_system" in build_combined_log(combined)


def test_combined_payload_rounds_numeric_results_to_six_decimal_places() -> None:
    combined = build_combined_payload(run_payload([
        scored_item("lax/lax.W1.k1", "UW-sys1", 0.430378),
        scored_item("manila/manila.W1.k1", "UW-sys1", 0.532969),
    ]))

    assert combined["overall_macro"]["bertscore"]["f1"] == 0.481674
    assert combined["primary_score"] == {
        "method": "mean_bertscore_f1_bleurt",
        "components": {"bertscore_f1": 0.481674, "bleurt": 0.481674},
        "score": 0.481674,
    }


def test_primary_score_means_rounded_bertscore_f1_and_bleurt() -> None:
    lax = scored_item("lax/lax.W1.k1", "UW-sys1", 0.430378)
    manila = scored_item("manila/manila.W1.k1", "UW-sys1", 0.532969)
    lax["summary"]["bleurt"]["micro"]["score"] = 0.341237
    manila["summary"]["bleurt"]["micro"]["score"] = 0.407121

    combined = build_combined_payload(run_payload([lax, manila]))

    assert combined["primary_score"] == {
        "method": "mean_bertscore_f1_bleurt",
        "components": {"bertscore_f1": 0.481674, "bleurt": 0.374179},
        "score": 0.427927,
    }


def test_primary_score_can_be_disabled() -> None:
    payload = run_payload([scored_item("lax/lax.W1.k1", "UW-sys1", 0.4)])
    payload["primary_score_config"]["enabled"] = False

    combined = build_combined_payload(payload)

    assert "primary_score" not in combined
    assert "Primary Score" not in build_combined_log(combined)


def test_sweep_run_does_not_define_one_primary_score() -> None:
    item = scored_item("lax/lax.W1.k1", "UW-sys1", 0.4)
    item["evaluation"] = {"view": "all_modes"}

    combined = build_combined_payload(run_payload([item]))

    assert "primary_score" not in combined
    assert "Primary Score" not in build_combined_log(combined)


def test_reporting_primary_score_configuration_is_validated(tmp_path: Path) -> None:
    config_path = tmp_path / "evaluation.yaml"
    config_path.write_text(
        """
reporting:
  primary_score:
    enabled: true
    method: unsupported
""".strip()
        + "\n",
        encoding="utf-8",
    )

    try:
        load_reporting_config(config_path)
    except ValueError as exc:
        assert "reporting.primary_score.method" in str(exc)
    else:
        raise AssertionError("unsupported primary score method was accepted")


def test_write_system_outputs_writes_instances_and_root_combined(tmp_path: Path) -> None:
    stale = tmp_path / "old.eval.json"
    stale.write_text("{}\n", encoding="utf-8")
    stale_combined = tmp_path / "combined.json"
    stale_combined.write_text("{}\n", encoding="utf-8")
    missing_lax = {
        "instance_id": "lax/lax.W1.k1",
        "crisis_id": "lax",
        "cell_id": "lax.W1.k1",
        "sys_id": "UW-sys1",
        "gold_file": "data/gold-output/lax/lax.W1.k1.report.json",
        "system_file": None,
        "status": "missing_system",
        "error": "missing system file for instance: lax/lax.W1.k1",
    }

    write_system_outputs(run_payload([missing_lax]), tmp_path)

    assert not stale.exists()
    assert not stale_combined.exists()
    assert (tmp_path / "lax" / "lax.W1.k1-eval.json").is_file()
    assert (tmp_path / "lax" / "lax.W1.k1-eval.log").is_file()
    assert (tmp_path / "combined-eval.json").is_file()
    assert (tmp_path / "combined-eval.log").is_file()
    assert not (tmp_path / "lax" / "combined-eval.json").exists()


def test_pair_outputs_omit_macro_but_combined_keeps_it(tmp_path: Path) -> None:
    item = scored_item("lax/lax.W1.k1", "UW-sys1", 0.4)
    item["evaluation"] = {
        "configured_metrics": {},
        "weighted_alignment": {},
    }
    item["structure_summary"] = {}
    write_system_outputs(
        run_payload([item]),
        tmp_path,
    )

    pair_json_path = tmp_path / "lax" / "lax.W1.k1-eval.json"
    pair_log_path = tmp_path / "lax" / "lax.W1.k1-eval.log"
    pair_payload = json.loads(pair_json_path.read_text(encoding="utf-8"))
    pair_json_text = pair_json_path.read_text(encoding="utf-8").lower()
    pair_log_text = pair_log_path.read_text(encoding="utf-8").lower()
    combined_json_text = (tmp_path / "combined-eval.json").read_text(
        encoding="utf-8"
    ).lower()
    combined_log_text = (tmp_path / "combined-eval.log").read_text(
        encoding="utf-8"
    ).lower()

    assert pair_payload["aggregation"] == {
        "level": "within_document",
        "method": "micro",
    }
    assert "macro" not in pair_json_text
    assert "macro" not in pair_log_text
    assert "across_documents" not in pair_json_text
    assert "overall_macro" in combined_json_text
    assert "overall macro results" in combined_log_text
