from __future__ import annotations

import sys
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from eval_sitrep import _score_configured_metric  # noqa: E402
from eval_pair import build_all_config_summary  # noqa: E402
from run_eval import build_log  # noqa: E402


def test_build_log_includes_release_diagnostics() -> None:
    payload = {
        "generated_at_utc": "2026-01-01T00:00:00+00:00",
        "config": "config/evaluation.yaml",
        "results": [{
            "instance_id": "collapse/collapse.W1.k1",
            "crisis_id": "collapse",
            "cell_id": "collapse.W1.k1",
            "sys_id": "UW-sys1",
            "gold_file": "data/gold-output/collapse/collapse.W1.k1.report.json",
            "system_file": (
                "data/sysId-output/UW-sys1/collapse/"
                "collapse.W1.k1.report.json"
            ),
            "status": "scored",
            "structure_summary": {
                "sections": {
                    "gold": 2, "system": 2, "matched": 1,
                    "unmatched_gold": 1, "unmatched_system": 1,
                },
                "subsections": {
                    "gold": 3, "system": 2, "matched": 2,
                    "unmatched_gold": 1, "unmatched_system": 0,
                },
                "bullets": {
                    "gold": 4, "system": 3, "matched": 2,
                    "unmatched_gold": 2, "unmatched_system": 1,
                },
            },
            "summary": {
                "rouge": {
                    "mode": "subsection",
                    "rouge1": {"fmeasure": 0.7},
                    "rouge2": {"fmeasure": 0.4},
                    "rougeL": {"fmeasure": 0.5},
                },
                "bertscore": {
                    "mode": "subsection",
                    "precision": 0.8,
                    "recall": 0.9,
                    "f1": 0.85,
                },
                "bleurt": {"mode": "subsection", "score": 0.3},
                "weighted_alignment": {
                    "scope": "subsection",
                    "metric": "rougeL",
                    "micro_soft_precision": 0.55,
                    "micro_soft_recall": 0.65,
                    "micro_soft_f1": 0.6,
                    "matched_pairs": 2,
                },
            },
            "evaluation": {
                "configured_metrics": {
                    "rouge": {
                        "mode": "subsection",
                        "status": "scored",
                        "warnings": [],
                        "diagnostics": {
                            "gold_units": 3,
                            "system_units": 2,
                            "matched_units": 2,
                            "skipped_both_empty_units": 1,
                            "denominator_policy": "whole_gold",
                            "rouge1": {
                                "gold_ngrams": 10,
                                "matched_gold_ngrams": 6,
                                "whole_gold_ngrams": 10,
                                "system_ngrams": 8,
                                "overlapping_ngrams": 4,
                            },
                            "rouge2": {
                                "gold_ngrams": 7,
                                "matched_gold_ngrams": 4,
                                "whole_gold_ngrams": 7,
                                "system_ngrams": 5,
                                "overlapping_ngrams": 2,
                            },
                            "rougeL": {
                                "gold_tokens": 10,
                                "matched_gold_tokens": 6,
                                "whole_gold_tokens": 10,
                                "system_tokens": 8,
                                "total_lcs_length": 4,
                            },
                        },
                    }
                },
                "weighted_alignment": {
                    "metric": "rougeL",
                    "status": "scored",
                    "warnings": [{"code": "sample_warning"}],
                    "configuration": {
                        "tweet_id_overlap": {
                            "enabled": True,
                            "text_weight": 0.8,
                        }
                    },
                    "groups": [{
                        "group_id": "3/3b",
                        "gold_count": 2,
                        "system_count": 2,
                        "matched_count": 1,
                        "soft_f1": 0.7,
                        "pairs": [{
                            "gold_bullet_id": "3b.1",
                            "system_bullet_id": "3b.2",
                            "weight": 0.66,
                            "text_similarity": 0.64,
                            "tweet_id_similarity": 0.75,
                            "gold_tweet_ids": ["1"],
                            "system_tweet_ids": ["1", "2"],
                            "gold_text": "gold fact",
                            "system_text": "system fact",
                        }],
                        "unmatched_gold": [{
                            "bullet_id": "3b.5",
                            "text": "missing gold",
                            "tweet_ids": [],
                        }],
                        "unmatched_system": [],
                    }],
                },
            },
        }],
    }

    log = build_log(payload)

    assert "LT4CPR Evaluation Log" in log
    assert "Evaluation Summary" in log
    assert "Instance ID         : collapse/collapse.W1.k1" in log
    assert "Crisis ID           : collapse" in log
    assert "Cell ID             : collapse.W1.k1" in log
    assert "Text-level Evaluation" in log
    assert "ROUGE (Subsection)" in log
    assert "ROUGE-1 F1  : 0.7000" in log
    assert "BERTScore (Subsection)" in log
    assert "F1          : 0.8500" in log
    assert "BLEURT (Subsection)" in log
    assert "Score       : 0.3000" in log
    assert "Bullet-level Hungarian Alignment (Subsection)" in log
    assert "Similarity metric   : rougeL + Tweet-ID overlap" in log
    assert "Soft F1             : 0.6000" in log
    assert "Structure Summary" in log
    assert "sections: gold=2 system=2 matched=1 unmatched_gold=1 unmatched_system=1" in log
    assert "ROUGE Diagnostics" in log
    assert "denominator_policy=whole_gold" in log
    assert "matched_units=2 scored_units=1 skipped_both_empty=1" in log
    assert "rouge1: gold_ngrams=10 system_ngrams=8 overlapping_ngrams=4" in log
    assert "Alignment Details" in log
    assert "Group 3/3b" in log
    assert "text_metric=rougeL text_similarity=0.6400" in log
    assert "tweet_id_jaccard=0.7500 text_weight=0.8000 final_edge_score=0.6600" in log
    assert "unmatched_gold:" in log
    assert 'id=3b.5 text="missing gold"' in log
    assert "unmatched_system: none" in log
    assert "Warnings" in log
    assert "missing_tweet_ids: gold_units=1 system_units=0" in log
    assert "warnings: sample_warning" in log


def test_rouge_whole_gold_denominator_penalizes_missing_gold_units() -> None:
    pairs = [
        {
            "unit_id": "section:1",
            "status": "matched",
            "candidate": "alpha",
            "reference": "alpha",
            "input_warnings": [],
        },
        {
            "unit_id": "section:2",
            "status": "reference_only",
            "candidate": "",
            "reference": "beta",
            "input_warnings": [],
        },
    ]

    matched_only = _score_configured_metric(
        "rouge",
        pairs,
        {
            "mode": 2,
            "aggregation": "micro",
            "denominator_policy": "matched_only",
        },
    )
    whole_gold = _score_configured_metric(
        "rouge",
        pairs,
        {
            "mode": 2,
            "aggregation": "micro",
            "denominator_policy": "whole_gold",
        },
    )

    assert matched_only["aggregates"]["micro"]["rouge1"]["recall"] == 1.0
    assert matched_only["aggregates"]["micro"]["rouge1"]["fmeasure"] == 1.0
    assert matched_only["diagnostics"]["rouge1"]["gold_ngrams"] == 1
    assert whole_gold["aggregates"]["micro"]["rouge1"]["recall"] == 0.5
    assert whole_gold["aggregates"]["micro"]["rouge1"]["fmeasure"] == 0.6667
    assert whole_gold["diagnostics"]["denominator_policy"] == "whole_gold"
    assert whole_gold["diagnostics"]["rouge1"]["gold_ngrams"] == 2


def test_all_config_summary_keeps_tweet_overlap_axis() -> None:
    def text_block(metric: str) -> dict:
        overall = (
            {"rougeL": {"fmeasure": 0.1}}
            if metric == "rouge"
            else {"f1": 0.2}
            if metric == "bertscore"
            else {"score": 0.3}
        )
        return {
            "mode": "document",
            "status": "scored",
            "aggregation": "micro",
            "n_scored": 1,
            "n_skipped_both_empty": 0,
            "overall": overall,
            "aggregates": {"macro": overall, "micro": overall},
        }

    def weighted_block(enabled: bool) -> dict:
        return {
            "metric": "rougeL",
            "threshold": 0.0,
            "status": "scored",
            "warnings": [],
            "configuration": {
                "unit_mode": "bullet",
                "tweet_id_overlap": {
                    "enabled": enabled,
                    "text_weight": 0.8 if enabled else 1.0,
                    "tweet_id_weight": 0.2 if enabled else 0.0,
                },
            },
            "summary": {
                "micro_soft_f1": 0.5 if enabled else 0.4,
                "micro_soft_precision": 0.5 if enabled else 0.4,
                "micro_soft_recall": 0.5 if enabled else 0.4,
                "structure_recall": 1.0,
                "structure_precision": 1.0,
                "matched_pairs": 1,
                "gold_units": 1,
                "system_units": 1,
                "warning_count": 0,
            },
        }

    payload = {
        "configured_metrics": {
            metric: {
                level: text_block(metric)
                for level in ("document", "section", "subsection")
            }
            for metric in ("rouge", "bertscore", "bleurt")
        },
        "weighted_alignment": {
            level: {
                unit_mode: {
                    metric: {
                        "off": weighted_block(False),
                        "on": weighted_block(True),
                    }
                    for metric in ("rougeL", "bertscore", "cosine")
                }
                for unit_mode in ("bullet", "text")
            }
            for level in ("document", "section", "subsection")
        },
    }

    summary = build_all_config_summary(payload)
    bullet_rows = [
        row for row in summary["rows"]
        if row["path"] == "bullet_level"
    ]

    assert len(bullet_rows) == 36
    assert {
        row["tweet_overlap"]
        for row in bullet_rows
        if row["level"] == "document"
        and row["unit_mode"] == "bullet"
        and row["metric"] == "rougeL"
    } == {"off", "on"}
    assert summary["weighted_alignment"]["document"]["bullet"]["rougeL"]["on"][
        "tweet_id_weight"
    ] == 0.2
