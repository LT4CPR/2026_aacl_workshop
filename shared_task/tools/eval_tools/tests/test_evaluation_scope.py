from __future__ import annotations

import json
import sys
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from eval_pair import evaluate_pair  # noqa: E402
import eval_sitrep  # noqa: E402
from eval_weighted_alignment import evaluate_one  # noqa: E402
from evaluation_scope import resolve_evaluation_scope  # noqa: E402
import run_eval  # noqa: E402
from run_eval import build_structure_summary  # noqa: E402
from sitrep_units import extract_units_by_group  # noqa: E402


def sitrep() -> dict:
    return {
        "sections": [
            {
                "id": "1",
                "title": "One",
                "subsections": [{
                    "id": "1a",
                    "title": "One A",
                    "bullets": [{"id": "1a.1", "text": "alpha"}],
                }],
            },
            {
                "id": "2",
                "title": "Two",
                "subsections": [{
                    "id": "2a",
                    "title": "Two A",
                    "bullets": [{"id": "2a.1", "text": "beta"}],
                }],
            },
        ]
    }


def write_config(path: Path, sections: str = '["1"]') -> None:
    path.write_text(
        f"""
evaluation_scope:
  sections: {sections}
reporting:
  primary_score:
    enabled: false
metrics:
  text_level:
    rouge:
      mode: 2
      aggregation: micro
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


def write_sitrep(path: Path) -> None:
    path.write_text(json.dumps(sitrep()) + "\n", encoding="utf-8")


def test_scope_config_and_cli_override_are_normalized(tmp_path: Path) -> None:
    config_path = tmp_path / "evaluation.yaml"
    write_config(config_path)

    configured = resolve_evaluation_scope(config_path)
    overridden = resolve_evaluation_scope(config_path, "2, 1,2")
    all_sections = resolve_evaluation_scope(config_path, "all")

    assert configured.section_ids == ("1",)
    assert configured.source == "config"
    assert overridden.section_ids == ("2", "1")
    assert overridden.source == "cli"
    assert all_sections.section_ids is None
    assert all_sections.source == "cli"


def test_selected_sections_filter_all_structural_modes() -> None:
    document = sitrep()

    document_units = extract_units_by_group(
        document, mode=1, unit_mode="bullet", selected_sections=("2",),
    ).units
    section_units = extract_units_by_group(
        document, mode=2, unit_mode="bullet", selected_sections=("2",),
    ).units
    subsection_units = extract_units_by_group(
        document, mode=3, unit_mode="bullet", selected_sections=("2",),
    ).units

    assert [unit["text"] for unit in document_units[("document", "document")]] == [
        "beta"
    ]
    assert set(section_units) == {("2", "section")}
    assert set(subsection_units) == {("2", "two a")}


def test_evaluate_pair_uses_config_scope_and_records_metadata(tmp_path: Path) -> None:
    config_path = tmp_path / "evaluation.yaml"
    gold_path = tmp_path / "sample-gold.json"
    system_path = tmp_path / "sample-sum.json"
    write_config(config_path)
    write_sitrep(gold_path)
    write_sitrep(system_path)

    result = evaluate_pair(gold_path, system_path, config_path)

    assert result["evaluation_scope"] == {"sections": ["1"], "source": "config"}
    rouge = result["configured_metrics"]["rouge"]
    assert [item["unit_id"] for item in rouge["items"]] == ["section:1"]
    assert rouge["overall"]["rouge1"]["fmeasure"] == 1.0


def test_weighted_alignment_uses_the_same_section_filter(tmp_path: Path) -> None:
    gold_path = tmp_path / "sample-gold.json"
    system_path = tmp_path / "sample-sum.json"
    write_sitrep(gold_path)
    write_sitrep(system_path)

    result = evaluate_one(
        gold_path,
        system_path,
        "test",
        0.1,
        lambda candidates, references, **kwargs: [1.0] * len(candidates),
        {},
        mode=2,
        selected_sections=("2",),
    )

    assert result["status"] == "scored"
    assert result["summary"]["gold_groups"] == 1
    assert result["summary"]["system_groups"] == 1
    assert [group["group_id"] for group in result["groups"]] == ["2"]


def test_structure_summary_counts_only_selected_sections(tmp_path: Path) -> None:
    gold_path = tmp_path / "sample-gold.json"
    system_path = tmp_path / "sample-sum.json"
    write_sitrep(gold_path)
    write_sitrep(system_path)

    summary = build_structure_summary(
        gold_path, system_path, selected_sections=("2",),
    )

    assert summary["sections"] == {
        "gold": 1,
        "system": 1,
        "matched": 1,
        "unmatched_gold": 0,
        "unmatched_system": 0,
    }
    assert summary["subsections"]["gold"] == 1
    assert summary["bullets"]["gold"] == 1


def test_run_eval_cli_sections_override_config_and_outputs_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    gold_dir = data_dir / "gold-output"
    system_dir = data_dir / "sysId-output" / "test-system"
    out_dir = data_dir / "eval-result" / "test-system"
    (gold_dir / "collapse").mkdir(parents=True)
    (system_dir / "collapse").mkdir(parents=True)
    config_path = tmp_path / "evaluation.yaml"
    write_config(config_path)
    write_sitrep(gold_dir / "collapse" / "collapse.W1.k1.report.json")
    write_sitrep(system_dir / "collapse" / "collapse.W1.k1.report.json")
    monkeypatch.setattr(sys, "argv", [
        "run_eval.py",
        "--data-dir", str(data_dir),
        "--system-id", "test-system",
        "--config", str(config_path),
        "--sections", "2",
    ])

    assert run_eval.main() == 0

    output = json.loads(
        (out_dir / "collapse" / "collapse.W1.k1-eval.json").read_text(
            encoding="utf-8"
        )
    )
    assert output["evaluation_scope"] == {"sections": ["2"], "source": "cli"}
    item = output["results"][0]
    assert item["structure_summary"]["sections"]["gold"] == 1
    assert [
        row["unit_id"]
        for row in item["evaluation"]["configured_metrics"]["rouge"]["items"]
    ] == ["section:2"]


def test_run_eval_handles_multiple_cells_within_one_crisis(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    gold_dir = data_dir / "gold-output"
    system_dir = data_dir / "sysId-output" / "test-system"
    out_dir = data_dir / "eval-result" / "test-system"
    config_path = tmp_path / "evaluation.yaml"
    write_config(config_path)

    instances = (
        ("collapse", "collapse.W1.k1"),
        ("collapse", "collapse.W1.k2"),
        ("tornado", "tornado.W1.k1"),
    )
    for crisis_id, cell_id in instances:
        gold_path = gold_dir / crisis_id / f"{cell_id}.report.json"
        system_path = system_dir / crisis_id / f"{cell_id}.report.json"
        gold_path.parent.mkdir(parents=True, exist_ok=True)
        system_path.parent.mkdir(parents=True, exist_ok=True)
        write_sitrep(gold_path)
        write_sitrep(system_path)

    monkeypatch.setattr(sys, "argv", [
        "run_eval.py",
        "--data-dir", str(data_dir),
        "--system-id", "test-system",
        "--config", str(config_path),
    ])

    assert run_eval.main() == 0

    for crisis_id, cell_id in instances:
        assert (out_dir / crisis_id / f"{cell_id}-eval.json").is_file()
        assert (out_dir / crisis_id / f"{cell_id}-eval.log").is_file()
    assert not (out_dir / "collapse" / "combined-eval.json").exists()

    combined = json.loads(
        (out_dir / "combined-eval.json").read_text(encoding="utf-8")
    )
    assert combined["instance_count"] == 3
    assert combined["scored_instance_count"] == 3
    assert combined["crisis_count"] == 2
    assert combined["crisis_ids"] == ["collapse", "tornado"]
    assert combined["coverage_ratio"] == 1.0
    assert combined["failed_instances"] == []


def test_run_eval_returns_nonzero_after_active_metric_runtime_failure(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    data_dir = tmp_path / "data"
    gold_dir = data_dir / "gold-output"
    system_dir = data_dir / "sysId-output" / "test-system"
    out_dir = data_dir / "eval-result" / "test-system"
    (gold_dir / "collapse").mkdir(parents=True)
    (system_dir / "collapse").mkdir(parents=True)
    config_path = tmp_path / "evaluation.yaml"
    config_path.write_text(
        """
evaluation_scope:
  sections: ["1"]
reporting:
  primary_score:
    enabled: false
metrics:
  text_level:
    rouge:
      mode: 0
    bertscore:
      mode: 2
      aggregation: micro
    bleurt:
      mode: 0
  bullet_level:
    mode: 0
""".strip()
        + "\n",
        encoding="utf-8",
    )
    write_sitrep(gold_dir / "collapse" / "collapse.W1.k1.report.json")
    write_sitrep(system_dir / "collapse" / "collapse.W1.k1.report.json")

    def fail_metric_load(*_args, **_kwargs):
        raise OSError("Operation not permitted: bert_score cache lock")

    monkeypatch.setattr(eval_sitrep, "_load_hf_metric", fail_metric_load)
    monkeypatch.setattr(sys, "argv", [
        "run_eval.py",
        "--data-dir", str(data_dir),
        "--system-id", "test-system",
        "--config", str(config_path),
    ])

    assert run_eval.main() == 1

    output_path = out_dir / "collapse" / "collapse.W1.k1-eval.json"
    assert output_path.is_file()
    output = json.loads(output_path.read_text(encoding="utf-8"))
    bertscore = output["results"][0]["evaluation"]["configured_metrics"]["bertscore"]
    assert bertscore["status"] == "skipped"
    assert "cache lock" in bertscore["error"]
    stderr = capsys.readouterr().err
    assert "incomplete evaluation" in stderr
    assert "collapse/collapse.W1.k1.configured_metrics.bertscore" in stderr


def test_run_eval_returns_nonzero_when_enabled_primary_score_is_null(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    data_dir = tmp_path / "data"
    gold_dir = data_dir / "gold-output"
    system_dir = data_dir / "sysId-output" / "test-system"
    out_dir = data_dir / "eval-result" / "test-system"
    (gold_dir / "collapse").mkdir(parents=True)
    (system_dir / "collapse").mkdir(parents=True)
    config_path = tmp_path / "evaluation.yaml"
    config_path.write_text(
        """
evaluation_scope:
  sections: ["1"]
reporting:
  primary_score:
    enabled: true
metrics:
  text_level:
    rouge:
      mode: 0
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
    write_sitrep(gold_dir / "collapse" / "collapse.W1.k1.report.json")
    write_sitrep(system_dir / "collapse" / "collapse.W1.k1.report.json")
    monkeypatch.setattr(sys, "argv", [
        "run_eval.py",
        "--data-dir", str(data_dir),
        "--system-id", "test-system",
        "--config", str(config_path),
    ])

    assert run_eval.main() == 1

    combined_path = out_dir / "combined-eval.json"
    assert combined_path.is_file()
    combined = json.loads(combined_path.read_text(encoding="utf-8"))
    assert combined["primary_score"]["score"] is None
    stderr = capsys.readouterr().err
    assert "combined.primary_score.score is not available" in stderr
