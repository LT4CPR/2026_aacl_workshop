# LT4CPR Evaluation

This directory contains the final release evaluator for structured LT4CPR
situation reports (SITREPs). One run evaluates one system against every
discovered Gold test instance across all crises and produces per-instance and
combined reports.

## Documentation

| Document | Contents |
| --- | --- |
| [`sample_data/README.md`](sample_data/README.md) | Input/output directories, filename conventions, crisis/cell pairing, and generated result files. |
| [`config/README.md`](config/README.md) | Available `evaluation.yaml` options and the meaning of each value. |
| [`src/README.md`](src/README.md) | Responsibility of each Python source file. |
| [`tests/`](tests/) | Release tests for pairing, aggregation, scope, output, and subsection alignment. |

## Installation

Run from `shared_task/tools/eval_tools/`. The release environment is tested
with Python 3.11.

```bash
conda create -n lt4cpr-eval python=3.11
conda activate lt4cpr-eval
python -m pip install -r requirements.txt
```

Git is required because BLEURT is installed from a fixed source commit. The
first run may download the configured BERTScore and BLEURT model files. The
optional cosine bullet-similarity mode may also download its configured
Sentence Transformers model.

## Input format

Each input is a schema-1.2 JSON object with `meta` and `sections`. Sections
contain subsections, and subsections contain bullets. A minimal example is:

```json
{
  "meta": {"schema_version": "1.2"},
  "sections": [
    {
      "id": "3",
      "title": "Casualties and human impact",
      "subsections": [
        {
          "id": "3a",
          "title": "Fatalities",
          "bullets": [
            {
              "id": "3a.1",
              "text": "One fatality was confirmed.",
              "confidence": "confirmed",
              "tweet_ids": [1234567890]
            }
          ]
        }
      ]
    }
  ]
}
```

Gold and System directories use the same official two-level layout:

```text
<root>/
└── <crisis>/
    └── <cell>.report.json
```

The evaluator pairs reports by the exact relative identity
`<crisis>/<cell>`. A crisis may contain any number of independent cells. The
crisis directory must be directly under the Gold or System root; an extra
`test/` directory is not accepted.

Each cell ID must follow `<crisis>.W<number>.k<number>`, where `W` identifies
the window and `k` identifies its replicate. The `<crisis>` prefix must match
the enclosing crisis directory so that hierarchical aggregation is unambiguous.

## Evaluation flow

```text
Gold directory + one System directory
                 │
                 ▼
      Pair files by crisis + cell ID
                 │
        ┌────────┴────────┐
        ▼                 ▼
  Text evaluation    Bullet evaluation
  ROUGE              Weighted similarity
  BERTScore          Hungarian alignment
  BLEURT             Soft precision/recall/F1
        └────────┬────────┘
                 ▼
     Per-instance JSON and log
                 │
                 ▼
       Combined system result
```

Use the provided `config/evaluation.yaml` unchanged for official shared-task
scoring. Detailed metric and aggregation options are documented in
[`config/README.md`](config/README.md).

Sections are aligned by exact section ID. Within an aligned section,
subsections can be aligned by subsection ID, normalized header, or both. The
release default is `header_only`; it does not require a hard-coded subsection
inventory.

BERTScore applies side-specific penalties to structurally unmatched content.
Gold-only subsection text contributes zero on the recall side while its Gold
token count remains in the recall denominator. System-only subsection text
contributes zero on the precision side while its System token count remains in
the precision denominator. BLEURT remains matched-only because it produces one
scalar score rather than separate precision and recall values.

## Run the evaluator

Activate the environment and run one system from this directory:

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

Run a separate command with a separate `--system-id` for each submitted
system. Use the following command to view all CLI options:

```bash
python src/run_eval.py --help
```

## Verify completion

A valid release evaluation must satisfy all of the following:

- the command exits with status `0`;
- `combined-eval.json` reports `coverage_ratio: 1.0`;
- `failed_instances` is empty;
- every active metric has `status: scored`; and
- the combined primary score is available.

The evaluator writes each cell's result under its crisis directory and writes
only one `combined-eval.json`/`.log` pair at the result root. The combined
score first averages replicates within each window, then windows within each
crisis/document, and finally crisis/documents with equal weight. A crisis with
more cells therefore does not receive more final weight. No per-crisis combined
files are generated.

The evaluator still writes diagnostic JSON/log files when possible after an
incomplete run, but exits with status `1`. Do not use a partial combined score
as an official result. Result locations and file contents are described in
[`sample_data/README.md`](sample_data/README.md).

## Tests

Run the release tests from this directory:

```bash
python -m pytest tests -q
```
