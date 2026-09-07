from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from eval_sitrep import evaluate_metric_pair, load_evaluation_config  # noqa: E402
from eval_weighted_alignment import (  # noqa: E402
    evaluate_one,
    load_hungarian_config,
)
from run_eval import build_structure_summary  # noqa: E402
from sitrep_units import UnitExtractionError, extract_units_by_group  # noqa: E402
from subsection_alignment import subsection_alignment_key  # noqa: E402


def sitrep(subsection_id: str, header: str, text: str = "same event") -> dict:
    return {
        "sections": [{
            "id": "3",
            "title": "Casualties and human impact",
            "subsections": [{
                "id": subsection_id,
                "title": header,
                "bullets": [{
                    "id": f"{subsection_id}.1",
                    "text": text,
                    "tweet_ids": [1],
                }],
            }],
        }],
    }


def write_sitrep(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document) + "\n", encoding="utf-8")


def rouge_spec(method: str) -> dict:
    return {
        "mode": 3,
        "aggregation": "micro",
        "denominator_policy": "whole_gold",
        "include_section_headers": False,
        "include_subsection_headers": False,
        "subsection_alignment_method": method,
    }


@pytest.mark.parametrize(
    ("method", "expected_key"),
    [
        ("id_only", "3c"),
        ("header_only", "missing persons"),
        (
            "both_id_and_header",
            subsection_alignment_key("3c", "Missing persons", "both_id_and_header"),
        ),
    ],
)
def test_bullet_extraction_supports_all_alignment_methods(
    method: str,
    expected_key: str,
) -> None:
    extracted = extract_units_by_group(
        sitrep("3c", "Missing persons"),
        mode=3,
        unit_mode="bullet",
        subsection_alignment_method=method,
    )

    assert set(extracted.units) == {("3", expected_key)}
    unit = extracted.units[("3", expected_key)][0]
    assert unit["subsection_id"] == "3c"
    assert unit["subsection_title"] == "Missing persons"


def test_header_only_is_dynamic_and_normalizes_case_and_whitespace() -> None:
    gold = extract_units_by_group(
        sitrep("3c", "  A Previously   Unseen Header "),
        mode=3,
        unit_mode="bullet",
        subsection_alignment_method="header_only",
    )
    system = extract_units_by_group(
        sitrep("3x", "a previously unseen header"),
        mode=3,
        unit_mode="bullet",
        subsection_alignment_method="header_only",
    )

    assert set(gold.units) == set(system.units) == {
        ("3", "a previously unseen header")
    }


@pytest.mark.parametrize(
    ("method", "expected_status"),
    [
        ("id_only", "skipped"),
        ("header_only", "scored"),
        ("both_id_and_header", "skipped"),
    ],
)
def test_text_metrics_use_configured_subsection_correspondence(
    tmp_path: Path,
    method: str,
    expected_status: str,
) -> None:
    gold_path = tmp_path / "sample-gold.json"
    system_path = tmp_path / "sample-sum.json"
    write_sitrep(gold_path, sitrep("3c", "Missing persons"))
    write_sitrep(system_path, sitrep("3b", "missing persons"))

    result = evaluate_metric_pair(
        system_path,
        gold_path,
        "rouge",
        rouge_spec(method),
    )

    assert result["status"] == expected_status
    assert result["subsection_alignment_method"] == method
    if expected_status == "scored":
        assert result["overall"]["rougeL"]["fmeasure"] == 1.0
        item = result["items"][0]
        assert item["candidate_subsection_id"] == "3b"
        assert item["reference_subsection_id"] == "3c"


@pytest.mark.parametrize(
    ("method", "expected_matches"),
    [
        ("id_only", 0),
        ("header_only", 1),
        ("both_id_and_header", 0),
    ],
)
def test_weighted_alignment_uses_the_same_correspondence_method(
    tmp_path: Path,
    method: str,
    expected_matches: int,
) -> None:
    gold_path = tmp_path / "sample-gold.json"
    system_path = tmp_path / "sample-sum.json"
    write_sitrep(gold_path, sitrep("3c", "Missing persons"))
    write_sitrep(system_path, sitrep("3b", "Missing persons"))

    result = evaluate_one(
        gold_path,
        system_path,
        "test",
        0.1,
        lambda candidates, references, **kwargs: [1.0] * len(candidates),
        {},
        mode=3,
        subsection_alignment_method=method,
    )

    assert result["summary"]["matched_pairs"] == expected_matches
    assert result["summary"]["unmatched_gold"] == 1 - expected_matches
    assert result["summary"]["unmatched_system"] == 1 - expected_matches


def test_id_only_preserves_matching_when_headers_disagree(tmp_path: Path) -> None:
    gold_path = tmp_path / "sample-gold.json"
    system_path = tmp_path / "sample-sum.json"
    write_sitrep(gold_path, sitrep("3c", "Missing persons"))
    write_sitrep(system_path, sitrep("3c", "Treatment and admissions"))

    id_result = evaluate_metric_pair(
        system_path, gold_path, "rouge", rouge_spec("id_only")
    )
    header_result = evaluate_metric_pair(
        system_path, gold_path, "rouge", rouge_spec("header_only")
    )

    assert id_result["status"] == "scored"
    assert id_result["overall"]["rougeL"]["fmeasure"] == 1.0
    assert header_result["status"] == "skipped"


def test_structure_summary_uses_the_configured_subsection_method(
    tmp_path: Path,
) -> None:
    gold_path = tmp_path / "sample-gold.json"
    system_path = tmp_path / "sample-sum.json"
    write_sitrep(gold_path, sitrep("3c", "Missing persons"))
    write_sitrep(system_path, sitrep("3b", "Missing persons"))

    id_summary = build_structure_summary(
        gold_path,
        system_path,
        subsection_alignment_method="id_only",
    )
    header_summary = build_structure_summary(
        gold_path,
        system_path,
        subsection_alignment_method="header_only",
    )

    assert id_summary["subsections"] == {
        "gold": 1,
        "system": 1,
        "matched": 0,
        "unmatched_gold": 1,
        "unmatched_system": 1,
    }
    assert header_summary["subsections"] == {
        "gold": 1,
        "system": 1,
        "matched": 1,
        "unmatched_gold": 0,
        "unmatched_system": 0,
    }


def test_header_only_rejects_duplicate_headers_within_a_section() -> None:
    document = sitrep("3b", "Missing persons")
    document["sections"][0]["subsections"].append({
        "id": "3c",
        "title": " missing   PERSONS ",
        "bullets": [],
    })

    with pytest.raises(UnitExtractionError, match="duplicate subsection alignment key"):
        extract_units_by_group(
            document,
            mode=3,
            unit_mode="bullet",
            subsection_alignment_method="header_only",
        )


def test_global_config_defaults_to_header_only(tmp_path: Path) -> None:
    config_path = tmp_path / "evaluation.yaml"
    config_path.write_text(
        """
metrics:
  text_level:
    rouge:
      mode: 3
    bertscore:
      mode: 0
    bleurt:
      mode: 0
  bullet_level:
    mode: 0
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = load_evaluation_config(config_path)

    assert config["rouge"]["subsection_alignment_method"] == "header_only"


def test_internal_entry_points_default_to_header_only(tmp_path: Path) -> None:
    gold_path = tmp_path / "sample-gold.json"
    system_path = tmp_path / "sample-sum.json"
    write_sitrep(gold_path, sitrep("3c", "Missing persons"))
    write_sitrep(system_path, sitrep("3b", "missing persons"))

    extracted = extract_units_by_group(
        sitrep("3c", "Missing persons"),
        mode=3,
        unit_mode="bullet",
    )
    assert set(extracted.units) == {("3", "missing persons")}

    text_spec = rouge_spec("id_only")
    text_spec.pop("subsection_alignment_method")
    text_result = evaluate_metric_pair(
        system_path,
        gold_path,
        "rouge",
        text_spec,
    )
    assert text_result["status"] == "scored"
    assert text_result["subsection_alignment_method"] == "header_only"

    weighted_result = evaluate_one(
        gold_path,
        system_path,
        "test",
        0.1,
        lambda candidates, references, **kwargs: [1.0] * len(candidates),
        {},
    )
    assert weighted_result["summary"]["matched_pairs"] == 1

    structure_summary = build_structure_summary(gold_path, system_path)
    assert structure_summary["subsections"]["matched"] == 1


def test_invalid_alignment_method_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "evaluation.yaml"
    config_path.write_text(
        """
subsection_alignment_method: fuzzy
metrics:
  text_level:
    rouge:
      mode: 3
    bertscore:
      mode: 0
    bleurt:
      mode: 0
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="subsection_alignment_method"):
        load_evaluation_config(config_path)


@pytest.mark.parametrize(
    "method",
    ["id_only", "header_only", "both_id_and_header"],
)
def test_bullet_level_config_accepts_all_alignment_methods(
    tmp_path: Path,
    method: str,
) -> None:
    config_path = tmp_path / "evaluation.yaml"
    config_path.write_text(
        f"""
subsection_alignment_method: {method}
metrics:
  bullet_level:
    mode: 3
    similarity_metric: rougeL
    alignment:
      threshold:
        rougeL: 0.1
        bertscore: 0.5
        cosine: 0.3
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = load_hungarian_config(config_path)

    assert config["subsection_alignment_method"] == method
