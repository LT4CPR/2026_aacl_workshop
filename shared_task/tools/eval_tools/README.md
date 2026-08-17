# LT4CPR Evaluation

This directory contains the final release evaluator for structured LT4CPR
situation reports (SITREPs). It evaluates one system against all discovered
disasters and writes per-disaster and combined results.

## 1. Installation

Run from `shared_task/tools/eval_tools/`. The release environment is tested with
Python 3.11.

```bash
conda create -n lt4cpr-eval python=3.11
conda activate lt4cpr-eval
python -m pip install -r requirements.txt
```

Git is required because BLEURT is installed from a fixed source commit. The
first run may download the configured BERTScore and BLEURT model files.

## 2. Input layout

```text
sample_data/
├── gold-output/
│   ├── blackout-gold.json
│   ├── conflict-gold.json
│   ├── crowdcrush-gold.json
│   └── epidemic-gold.json
└── sysId-output/
    └── UW-sys1/
        ├── blackout-sum.json
        ├── conflict-sum.json
        ├── crowdcrush-sum.json
        └── epidemic-sum.json
```

Gold filenames must end in `-gold.json`. System filenames must end in
`-sum.json`. Files are paired by the preceding disaster ID, such as `blackout`.

Each file must contain structured sections, subsections, and bullets:

```json
{
  "sections": [
    {
      "id": "3",
      "title": "Casualties",
      "subsections": [
        {
          "id": "3.1",
          "title": "Deaths",
          "bullets": [
            {
              "id": "3.1.1",
              "text": "Five people were reported dead.",
              "tweet_ids": ["1234567890"]
            }
          ]
        }
      ]
    }
  ]
}
```

Every section or subsection containing at least one bullet must have an `id`.
Header-only containers with no bullets are ignored and do not require IDs.
Every scorable bullet should contain `text`; `tweet_ids` is optional.

## 3. Official evaluation policy

- Only Sections 3--11 are scored. Sections 1 and 2 may appear in a SITREP but
  never enter the score.
- Section and subsection IDs are structural keys; titles are not scored.
- The release configuration evaluates text and bullets at subsection level.
- If a subsection exists on both sides, its content is compared normally.
- A Gold-only subsection is a system omission and receives score `0`.
- A System-only subsection is an unnecessary addition and receives score `0`.
- A header with no bullets on either side is not a scoring unit.
- If no usable Sections 3--11 hierarchy exists, the submission is marked
  `incomplete`; it is excluded from combined aggregation and the command exits
  with status `1`.

Text-level metrics are ROUGE-1/2/L, BERTScore, and BLEURT. The official ROUGE
policy is `denominator_policy: whole_gold`, which includes all Gold text in the
micro recall denominator and all System text in the micro precision
denominator.

Bullet-level evaluation computes pairwise similarity, combines ROUGE-L with
Tweet-ID Jaccard overlap using the configured weights, and performs maximum-
weight one-to-one Hungarian matching. Unmatched Gold and System bullets remain
in the recall and precision denominators, respectively.

Within each disaster, the release score uses micro aggregation. Combined
results use an equal-weight macro average across successfully scored disasters.
The primary score is:

```text
primary_score = (BERTScore_F1 + BLEURT) / 2
```

## 4. Run the evaluator

From `shared_task/tools/eval_tools/`:

```bash
conda activate lt4cpr-eval

python src/run_eval.py \
  --data-dir sample_data \
  --system-id UW-sys1 \
  --config config/evaluation.yaml
```

Equivalent explicit paths are:

```bash
python src/run_eval.py \
  --gold-dir sample_data/gold-output \
  --sys-dir sample_data/sysId-output/UW-sys1 \
  --out-dir sample_data/eval-result/UW-sys1 \
  --system-id UW-sys1 \
  --config config/evaluation.yaml
```

Use a separate system directory and `--system-id` for each submitted system.
Existing evaluator output files in the selected output directory are replaced
by the new run.

## 5. Output

The command above writes:

```text
sample_data/eval-result/UW-sys1/
├── blackout-eval.json
├── blackout-eval.log
├── conflict-eval.json
├── conflict-eval.log
├── crowdcrush-eval.json
├── crowdcrush-eval.log
├── epidemic-eval.json
├── epidemic-eval.log
├── combined-eval.json
└── combined-eval.log
```

- `*-eval.json`: complete machine-readable metric results and diagnostics
- `*-eval.log`: human-readable result for one disaster
- `combined-eval.json`: coverage and equal-weight macro results
- `combined-eval.log`: human-readable combined result

A successful run exits with status `0`. It exits with status `1` after writing
diagnostic output if an input is missing, a disaster is incomplete, an active
metric is not `scored`, or the primary score is unavailable. Check
`coverage_ratio`, `failed_disasters`, metric `status`, and warnings before using
the combined score.
