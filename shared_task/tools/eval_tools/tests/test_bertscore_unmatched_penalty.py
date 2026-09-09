from __future__ import annotations

import sys
from pathlib import Path

import pytest


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

import eval_sitrep  # noqa: E402


class FakeBERTScore:
    def compute(self, **_: object) -> dict[str, object]:
        return {
            "precision": [0.8],
            "recall": [0.6],
            "f1": [0.685714],
            "hashcode": "fake-bertscore",
        }


def bertscore_spec(aggregation: str = "micro") -> dict[str, object]:
    return {
        "mode": 3,
        "aggregation": aggregation,
        "model_type": "fake-model",
        "batch_size": 1,
    }


def unmatched_pairs() -> list[dict[str, str]]:
    return [
        {
            "unit_id": "subsection:3/matched",
            "status": "matched",
            "candidate": "one two",
            "reference": "one two three four",
        },
        {
            "unit_id": "subsection:3/system-only",
            "status": "candidate_only",
            "candidate": "extra words here",
            "reference": "",
        },
        {
            "unit_id": "subsection:3/gold-only",
            "status": "reference_only",
            "candidate": "",
            "reference": "missing reference",
        },
    ]


def test_bertscore_micro_applies_side_specific_zero_penalties(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(eval_sitrep, "_apply_bertscore_tokenizer_compat", lambda: None)
    monkeypatch.setattr(eval_sitrep, "_load_hf_metric", lambda _: FakeBERTScore())

    result = eval_sitrep._score_configured_metric(
        "bertscore", unmatched_pairs(), bertscore_spec()
    )

    # Precision: (0.8 * 2 matched System tokens + 0 * 3 System-only tokens) / 5.
    # Recall: (0.6 * 4 matched Gold tokens + 0 * 2 Gold-only tokens) / 6.
    assert result["overall"] == {
        "precision": 0.32,
        "recall": 0.4,
        "f1": 0.355556,
        "model_type": "fake-model",
        "unmatched_policy": "side_specific_zero",
        "hashcode": "fake-bertscore",
    }
    assert result["unmatched_penalty"] == {
        "policy": "side_specific_zero",
        "matched_system_token_weight": 2,
        "system_only_units": 1,
        "system_only_token_weight": 3,
        "precision_denominator_token_weight": 5,
        "matched_gold_token_weight": 4,
        "gold_only_units": 1,
        "gold_only_token_weight": 2,
        "recall_denominator_token_weight": 6,
    }


def test_bertscore_macro_applies_side_specific_zero_penalties(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(eval_sitrep, "_apply_bertscore_tokenizer_compat", lambda: None)
    monkeypatch.setattr(eval_sitrep, "_load_hf_metric", lambda _: FakeBERTScore())

    result = eval_sitrep._score_configured_metric(
        "bertscore", unmatched_pairs(), bertscore_spec("macro")
    )

    assert result["overall"]["precision"] == 0.4
    assert result["overall"]["recall"] == 0.3
    assert result["overall"]["f1"] == 0.342857


def test_bertscore_scores_all_unmatched_nonempty_units_as_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        eval_sitrep,
        "_load_hf_metric",
        lambda _: pytest.fail("BERTScore inference must not run without matched pairs"),
    )
    pairs = [
        {
            "unit_id": "subsection:3/system-only",
            "status": "candidate_only",
            "candidate": "system text",
            "reference": "",
        },
        {
            "unit_id": "subsection:3/gold-only",
            "status": "reference_only",
            "candidate": "",
            "reference": "gold text",
        },
    ]

    result = eval_sitrep._score_configured_metric(
        "bertscore", pairs, bertscore_spec()
    )

    assert result["status"] == "scored"
    assert result["n_scored"] == 0
    assert result["overall"]["precision"] == 0.0
    assert result["overall"]["recall"] == 0.0
    assert result["overall"]["f1"] == 0.0


def test_bleurt_remains_matched_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eval_sitrep, "_score_bleurt", lambda *_: [0.5])
    spec = {"mode": 3, "aggregation": "micro", "config_name": "fake"}

    result = eval_sitrep._score_configured_metric(
        "bleurt", unmatched_pairs(), spec
    )

    assert result["overall"]["score"] == 0.5
    assert "unmatched_penalty" not in result
