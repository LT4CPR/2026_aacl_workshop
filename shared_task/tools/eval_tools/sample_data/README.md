# Sample Data Directory

This directory demonstrates the evaluation layout for the official shared-task
test format using examples derived from the released training data. There is no
separate `train/` directory under `sample_data/`; its three data directories are
`gold-output/`, `sysId-output/`, and `eval-result/`.

`sysId-output/<system-id>/` demonstrates the per-system portion of a participant
submission after the team ZIP has been validated and extracted. It is an example
of the directory and filename layout accepted by the evaluator, rather than a
complete participant ZIP with `submission.json`. The evaluator reads only
`gold-output/` and the selected directory under `sysId-output/`; it never reads
the original training inputs during scoring.

## Directory structure

```text
sample_data/
├── gold-output/
│   ├── <crisis-1>/
│   │   ├── <cell-1>.report.json
│   │   └── <cell-2>.report.json
│   └── <crisis-2>/
│       └── <cell-3>.report.json
├── sysId-output/
│   └── <system-id>/
│       ├── <crisis-1>/
│       │   ├── <cell-1>.report.json
│       │   └── <cell-2>.report.json
│       └── <crisis-2>/
│           └── <cell-3>.report.json
└── eval-result/
    └── <system-id>/
        ├── <crisis-1>/
        │   ├── <cell-1>-eval.json
        │   ├── <cell-1>-eval.log
        │   ├── <cell-2>-eval.json
        │   └── <cell-2>-eval.log
        ├── <crisis-2>/
        │   ├── <cell-3>-eval.json
        │   └── <cell-3>-eval.log
        ├── combined-eval.json
        └── combined-eval.log
```

One crisis can contain multiple independent test instances. For example, the
Gold and System files below form one evaluation pair:

```text
gold-output/tornado/tornado.W2.k3.report.json
sysId-output/retrieval-llm/tornado/tornado.W2.k3.report.json
```

Pairing uses the complete relative identity `tornado/tornado.W2.k3`. Matching
only a filename or only a crisis name is insufficient. A missing Gold or
System counterpart makes that specific instance incomplete.

The crisis directories must be direct children of `gold-output/` and each
`sysId-output/<system-id>/` directory. Do not insert an additional `test/`
layer. Input filenames must end in `.report.json`.

## Evaluation results

For every discovered instance, the evaluator mirrors the crisis directory and
writes `<cell>-eval.json` plus `<cell>-eval.log`. It does not create a
crisis-level combined file.

At the system result root, `combined-eval.json` and `combined-eval.log` combine
all cells from all crises. The combined metrics are equal-weight macro averages
over successfully scored test instances. Consequently, every cell has equal
weight; a crisis with more cells contributes more cells to the final average.

`combined-eval.json` records `crisis_ids`, `instance_ids`, instance coverage,
failed instances, the overall macro metrics, and the primary score. A complete
official run must have `coverage_ratio: 1.0` and an empty `failed_instances`
list.

The evaluator creates `eval-result/<system-id>/` when needed and replaces
evaluator-generated result files from an earlier run. Every result records the
evaluation scope and subsection-alignment method for auditing.
