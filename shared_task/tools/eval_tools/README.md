# LT4CPR Evaluation

This directory contains the final release evaluator for structured LT4CPR
situation reports (SITREPs). One run evaluates one system against all
discovered Gold disasters and produces per-disaster and combined reports.

## Documentation

| Document | Contents |
| --- | --- |
| [`sample_data/README.md`](sample_data/README.md) | Input/output directories, filename conventions, disaster pairing, and generated result files. |
| [`config/README.md`](config/README.md) | Available `evaluation.yaml` options and the meaning of each value. |
| [`src/README.md`](src/README.md) | Responsibility of each Python source file. |
| [`../../data/DATA_FORMAT.md`](../../data/DATA_FORMAT.md) | Structured SITREP JSON format. |

## Installation

Run from `shared_task/tools/eval_tools/`. The release environment is tested
with Python 3.11.

```bash
conda create -n lt4cpr-eval python=3.11
conda activate lt4cpr-eval
python -m pip install -r requirements.txt
```

Git is required because BLEURT is installed from a fixed source commit. The
first run may download the configured BERTScore and BLEURT model files.

## Evaluation flow

```text
Gold directory + one System directory
                 │
                 ▼
       Pair files by disaster ID
                 │
        ┌────────┴────────┐
        ▼                 ▼
  Text evaluation    Bullet evaluation
  ROUGE              Weighted similarity
  BERTScore          Hungarian alignment
  BLEURT             Soft precision/recall/F1
        └────────┬────────┘
                 ▼
     Per-disaster JSON and log
                 │
                 ▼
       Combined system result
```

Use the provided `config/evaluation.yaml` unchanged for official shared-task
scoring. Detailed metric and aggregation options are documented in
[`config/README.md`](config/README.md).

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
- `failed_disasters` is empty;
- every active metric has `status: scored`; and
- the combined primary score is available.

The evaluator still writes diagnostic JSON/log files when possible after an
incomplete run, but exits with status `1`. Do not use a partial combined score
as an official result. Result locations and file contents are described in
[`sample_data/README.md`](sample_data/README.md).
