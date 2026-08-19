# Sample Data Directory

This directory shows the input and output layout expected by the evaluator.
It documents directory placement and filename conventions rather than the
internal SITREP JSON schema.

## Directory structure

```text
sample_data/
├── gold-output/
│   └── <disaster-id>-gold.json
├── sysId-output/
│   └── <system-id>/
│       └── <disaster-id>-sum.json
└── eval-result/
    └── <system-id>/
        ├── <disaster-id>-eval.json
        ├── <disaster-id>-eval.log
        ├── combined-eval.json
        └── combined-eval.log
```

Each input directory may contain multiple disaster files. Each participating
system must use a separate `<system-id>` directory under `sysId-output/`.
Evaluation results for that system are written to the matching `<system-id>`
directory under `eval-result/`.

## Input filenames

| Directory | Filename format | Contents |
| --- | --- | --- |
| `gold-output/` | `<disaster-id>-gold.json` | One Gold SITREP for a disaster. |
| `sysId-output/<system-id>/` | `<disaster-id>-sum.json` | One System SITREP for the same disaster. |

The evaluator pairs files by the exact `<disaster-id>` prefix. For example:

```text
gold-output/blackout-gold.json
sysId-output/UW-sys1/blackout-sum.json
```

Both files form the `blackout` evaluation pair. Input JSON files must be direct
children of their respective directories and must use the required suffix.
A missing Gold or System counterpart makes that disaster incomplete.

## Evaluation-result filenames

For every discovered disaster pair, the evaluator writes:

| Filename | Contents |
| --- | --- |
| `<disaster-id>-eval.json` | Machine-readable metrics, scores, warnings, and diagnostics for one Gold/System pair. |
| `<disaster-id>-eval.log` | Human-readable evaluation report for the same pair. |

After all disaster pairs have been processed, the evaluator also writes:

| Filename | Contents |
| --- | --- |
| `combined-eval.json` | Machine-readable coverage, failed-disaster information, across-disaster macro results, and the primary score. |
| `combined-eval.log` | Human-readable summary of the combined evaluation. |

The evaluator creates the `eval-result/<system-id>/` directory when needed and
replaces evaluator output files from an earlier run in that directory.
