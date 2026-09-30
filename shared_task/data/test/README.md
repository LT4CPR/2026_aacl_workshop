# LT4CPR Shared Task — Test Data Release

This post-evaluation release contains synthetic crisis-related social-media
inputs, reference situation reports, baseline outputs, participant submissions,
and evaluation results. All events, people, locations, organizations, and
messages are fictional; this dataset does not document real emergencies.

## Contents

```text
test/
├── README.md
├── test.zip                         # Inputs: test/<crisis>/*.tweets.jsonl
├── reference/<crisis>/*.report.json
├── baseline-systems/
│   ├── baseline-sys1/<stage>/<grouping>/<crisis>/*.report.json
│   ├── baseline-sys1-eval/<stage>/<grouping>/
│   ├── baseline-sys2/<model>/<level>/<crisis>/*.report.json
│   └── baseline-sys2-eval/<model>/<level>/
├── team-submissions/<team-id>/<system-id>/<crisis>/*.report.json
└── team-submission-eval/<team-id>/<system-id>/
```

`test.zip` is the released input archive; extracting it creates `test/`.
There are **117 inputs and 117 reference reports** across six crises:

| Crisis | Instances |
|---|---:|
| `collapse` | 19 |
| `damsafety` | 19 |
| `heatwave` | 13 |
| `indfire` | 16 |
| `landslide` | 28 |
| `tornado` | 22 |
| **Total** | **117** |

The release includes **35 system runs**: 4 Baseline 1 configurations,
15 Baseline 2 configurations, and 16 participant systems. Each output root
contains 117 reports. Its matching evaluation root contains
`<crisis>/<cell>-eval.json` and `<crisis>/<cell>-eval.log` for all 117 instances,
plus `combined-eval.json` and `combined-eval.log`.

Baseline 1 uses the same relative configuration paths under `baseline-sys1/`
and `baseline-sys1-eval/`:

| Configuration | System ID |
|---|---|
| `w-stage2/w-grouping` | `UW-sys1` |
| `w-stage2/wo-grouping` | `UW-sys18` |
| `wo-stage2/w-grouping` | `UW-sys39` |
| `wo-stage2/wo-grouping` | `UW-sys40` |

`w-stage2` enables Stage 2; `wo-stage2` disables it. `w-grouping` and
`wo-grouping` indicate whether grouping is enabled.

## Inputs and Instance Identity

Each `<crisis>/<cell>.tweets.jsonl` starts with crisis metadata, then window
metadata, followed by message records with these core fields:

```json
{"id": 42, "text": "Example message.", "information_source": "Media", "timestamp": "Tue Jul 08 19:57:44 +0000 2025"}
```

`information_source` uses categories such as `Government`, `Media`,
`Eyewitness`, `NGOs`, `Outsiders`, and `Not labeled`.
Cell names follow `<crisis>.W<number>.k<number>` (window and replicate),
for example `tornado.W2.k3`.

- Process each file independently and leave the released inputs unchanged.
- Message IDs are positive integers **local to that file**; the same ID in
  another file need not identify the same message.
- Use only facts supported by the current input, respecting its temporal scope.
  Do not import information from other windows, replicates, crises, or hidden
  reference reconstructions.

## Report Format

Produce one UTF-8 JSON report per input, preserving the crisis directory and
cell stem: `<crisis>/<cell>.tweets.jsonl` → `<crisis>/<cell>.report.json`.
Do not add team or system IDs to report filenames.

Reports use `meta.schema_version: "1.2"` and the hierarchy
`sections → subsections → bullets`. A format-only example is:

```json
{
  "meta": {"schema_version": "1.2"},
  "sections": [{
    "id": "3",
    "title": "Casualties and human impact",
    "subsections": [{
      "id": "3b",
      "title": "Injuries",
      "bullets": [{
        "id": "3b.1",
        "text": "People were injured.",
        "confidence": "confirmed",
        "tweet_ids": [17, 22]
      }]
    }]
  }]
}
```

Only Sections **1–11** belong in participant reports; internal Sections 12–15
and construction-time identifiers/metadata must not be included.

| ID | Section |
|---|---|
| `1` | Situation overview |
| `2` | Timeline |
| `3` | Casualties and human impact |
| `4` | Infrastructure and service impact |
| `5` | Displacement and movement |
| `6` | Hazard assessment |
| `7` | Response actions |
| `8` | Communication and information |
| `9` | Aid and relief |
| `10` | Organizational and administrative activity |
| `11` | Social and community response |

Follow the official template and [training](../train/README.md)/
[development](../dev/README.md) reports for the section/subsection hierarchy.
Empty sections or subsections may be omitted, subject to the official validator.
Every bullet must contain:

- `id`: unique within the report and consistent with its subsection, e.g.
  `3b.1`, `3b.2`. Number your own bullets; do not guess reference bullet IDs.
- `text`: a concise supported claim, with redundant messages consolidated.
- `confidence`: exactly `confirmed` or `unconfirmed`. Negation belongs in the
  text, not in a separate confidence label.
- `tweet_ids`: a duplicate-free array of integer IDs from the **matching input**
  that support the full claim. Factual bullets should normally cite at least
  one message; internal IDs such as `SYN_...` are not valid evidence IDs.

## Submission and Validation

The submitted team ZIP format is distinct from the release layout above:

```text
<team_id>.zip
└── <team_id>/
    ├── submission.json
    └── systems/<system_id>/<crisis>/<cell>.report.json
```

Each system must independently contain all 117 reports, with crisis directories
directly under `<system_id>/` (**no extra `test/` layer**). Include only the
manifest and reports: no inputs, code, logs, models, prompts, cached responses,
links to another run, or internal metadata.

Minimal `submission.json`:

```json
{
  "submission_format_version": "1.0",
  "team": {"id": "example-team", "name": "Example Team"},
  "systems": [{"id": "system-1", "name": "System 1", "primary": true}]
}
```

Team/system IDs must match `[a-z0-9][a-z0-9_-]*`; names must be non-empty.
`team.id` must match the ZIP's top-level directory. Declared system IDs must be
unique and match `systems/` directories exactly. Exactly one system must have
`primary: true`; additional complete systems may have `primary: false`.

Run the [official validator](../../tools/other_tools/validate_submission.py)
from `shared_task/` before submission:

```bash
python3 tools/other_tools/validate_submission.py \
    --submission path/to/<team_id>.zip \
    --test-data data/test/test.zip
```

`--test-data` also accepts extracted inputs. The validator checks package
structure, manifest, exact coverage, report schema, hierarchy, confidence, and
evidence IDs—not whether the cited messages semantically support each claim.
Exit codes: `0` valid, `1` invalid, `2` validator/configuration error.

## Evaluation and Use

Released results compare system reports against `reference/`. See the
[evaluation documentation](../../tools/eval_tools/README.md) for metrics,
configuration, and reproduction instructions. Different windows/replicates of
the same crisis can support different reports.

This benchmark is for research, not evidence of safe real-world emergency
deployment without further validation and human oversight. Latest official
shared-task instructions and the official validator take precedence if they
conflict with this README.
