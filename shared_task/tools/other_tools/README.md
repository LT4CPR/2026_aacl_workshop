# Other tools

Utility and analysis tools for the shared task. These include participant
submission validation and corpus-analysis scripts. For viewing tweets and
reports, see `tools/visualization_tools/`.

| Tool | Purpose |
| --- | --- |
| `validate_submission.py` | Validate a team submission ZIP, including team/system metadata, file coverage, report structure, and evidence tweet IDs. |
| `audit_faithfulness.py` | Measure how well each reference statement is supported by the tweets cited for it. |

Paths below assume the layout:

```
shared_task/
├── data/
│   ├── train/{crisis}/...
│   ├── dev/{crisis}/...
│   └── test/{crisis}/...
└── tools/
    ├── other_tools/
    │   ├── README.md
    │   ├── validate_submission.py
    │   └── audit_faithfulness.py
    └── visualization_tools/
```

Commands are written to run from `shared_task/`.

---


## validate_submission.py

### What it checks

`validate_submission.py` checks whether a participant submission follows the
official team-level submission format.

One ZIP represents one team and may contain one or more complete system runs.
The expected structure is:

```text
<team_id>.zip
└── <team_id>/
    ├── submission.json
    └── systems/
        ├── <system_id_1>/
        │   └── test/
        │       ├── collapse/
        │       ├── damsafety/
        │       ├── heatwave/
        │       ├── indfire/
        │       ├── landslide/
        │       └── tornado/
        └── <system_id_2>/
            └── test/
                └── ...
```

Each system must provide exactly one `.report.json` file for every released
test input.

The validator derives the expected cells and valid tweet IDs directly from the
released test data, rather than relying only on a hard-coded file count.

It checks:

- ZIP path safety and the single top-level team directory;
- `submission.json` syntax and required fields;
- machine-readable team and system IDs;
- agreement between the manifest and the directories under `systems/`;
- exactly one `primary: true` system;
- complete report coverage for every declared system;
- absence of unexpected report or auxiliary files;
- valid UTF-8 JSON;
- participant report schema version `1.2`;
- Sections 1–11 only, in valid hierarchy/order;
- section, subsection, and bullet ID consistency;
- bullet fields `id`, `text`, `confidence`, and `tweet_ids`;
- binary confidence values: `confirmed` or `unconfirmed`;
- integer evidence IDs that actually occur in the corresponding test input;
- duplicate evidence IDs;
- obvious leakage of internal identifiers such as `SYN_...`, `EV_CAN_...`,
  `E_CAN_...`, or construction-time metadata.

The validator checks **format and referential integrity**. It does not determine
whether a generated statement is factually supported by its cited tweets; use
`audit_faithfulness.py` or the official evaluation tools for semantic analysis.

### Requirements

Python standard library only. No additional packages are required.

### `submission.json`

A submission manifest looks like:

```json
{
  "submission_format_version": "1.0",
  "team": {
    "id": "uw-crisisnlp",
    "name": "UW CrisisNLP"
  },
  "systems": [
    {
      "id": "retrieval-llm",
      "name": "Retrieval + LLM",
      "primary": true
    },
    {
      "id": "zero-shot-llm",
      "name": "Zero-shot LLM",
      "primary": false
    }
  ]
}
```

Team and system IDs must match:

```text
[a-z0-9][a-z0-9_-]*
```

Human-readable names may contain spaces and normal punctuation.

Exactly one system must be marked as the team's primary system.

### Usage

Run from `shared_task/`:

```bash
python3 tools/other_tools/validate_submission.py \
    --submission path/to/uw-crisisnlp.zip \
    --test-data data/test
```

The `--test-data` argument may also point to the released test ZIP instead of
an extracted directory:

```bash
python3 tools/other_tools/validate_submission.py \
    --submission path/to/uw-crisisnlp.zip \
    --test-data path/to/test.zip
```

### Output and exit codes

A valid submission prints:

```text
VALID — submission passed all checks against 117 test cells.
```

An invalid submission prints all detected validation errors and exits nonzero.

| Exit code | Meaning |
| ---: | --- |
| `0` | Submission is valid |
| `1` | Submission is invalid |
| `2` | Validator/configuration error, such as unreadable test data |

### Important submission rules

For each declared system:

- every released test input must have exactly one matching report;
- the report filename must preserve the input cell stem;
- report files must appear under
  `<team_id>/systems/<system_id>/test/<crisis>/`;
- systems may not submit only differences relative to another system;
- evidence IDs are local to each test cell and must come from that cell's
  `.tweets.jsonl` file;
- internal pipeline IDs must never appear in participant output.

The validator should be run before uploading a submission to the official
submission platform.

---

## audit_faithfulness.py

### What it measures

A reference statement is kept in a cell when that cell contains a tweet
reporting the event the statement describes. That guarantees the event is
present. It does not guarantee the tweets state every detail the statement
carries.

This tool measures the difference. Each statement is decomposed into atomic
claims, and each claim is scored against the tweets cited for that statement
using natural language inference: the tweets are the premise, the claim is the
hypothesis, and the model judges whether the premise entails it.

The result tells you how much of the reference is recoverable from the input,
which bounds what any system can achieve.

### Requirements

```bash
pip install transformers torch
```

The default model is `microsoft/deberta-large-mnli`, downloaded on first run
(about 1.6 GB). Any sequence-classification model with entailment, neutral, and
contradiction labels works; the label order is read from the model
configuration rather than assumed.

A GPU is used if available. On CPU, expect a few minutes per few hundred
claims, so start with `--limit`.

### Usage

```bash
python3 tools/other_tools/audit_faithfulness.py \
    --export-dir data \
    --split train \
    --limit 300 \
    --out-json faithfulness.json
```

| Option | Effect |
| --- | --- |
| `--export-dir` | Directory holding the split folders |
| `--split` | `train` or `dev` (default `train`) |
| `--sections` | Comma-separated section ids (default `3,...,11`, the scored sections) |
| `--model` | Any MNLI-style checkpoint |
| `--limit N` | Sample N statements; `0` scores all |
| `--batch-size` | Claims per forward pass (default 16) |
| `--out-json` | Write the full per-claim results |

### Reading the output

Every statement falls into one of five states:

| State | Meaning |
| --- | --- |
| `supported` | Every claim in the statement is entailed by the cited tweets |
| `partly_supported` | Some but not all claims are entailed |
| `unsupported` | No claim is entailed, and none contradicted |
| `contradicted` | A claim is contradicted by the cited tweets |
| `no_evidence` | The statement cites no tweets |

The summary reports the distribution, mean and median claim coverage, and a
breakdown by document and by section giving both **full** support (every claim
entailed) and **any** support (at least one).

### Why decomposition matters

Report statements routinely carry more than one claim:

> Emergency chlorination was started **and** chlorine residual returned to
> target range at the reservoir outlet.

Entailment of a compound sentence fails whenever any conjunct is unsupported,
so scoring the whole statement reports `neutral` even when the evidence states
one conjunct almost verbatim. In this corpus 44 percent of statements carry more
than one claim, and without decomposition the measure is dominated by that
effect: an early run scored 6.5 percent supported, which reflected the metric
rather than the data.

Decomposition splits on coordinated clauses, semicolons, and trailing
participial modifiers, merging any segment that carries no verb back into the
one before it, so a conjoined noun phrase is not treated as a separate claim.

### Two cautions

**Contradiction judgments are unreliable on this data.** The premise is a
concatenation of informal posts, which is far from the clean sentence pairs
these models are trained on. Spot checks found confident contradictions that are
not contradictions, for example a statement that no structures beyond the
transformers were destroyed scored as contradicting a tweet reporting that the
substation fire had been extinguished. Treat contradictions as cases to inspect,
not as counts to report.

**Paraphrase can go unrecognized.** A claim may be stated in the tweets in
wording the model does not connect to the statement. The measure is therefore a
lower bound on support rather than an exact figure.

Both cautions argue for reading the per-claim output in `--out-json` rather than
relying on the headline percentages alone.

### Using it on system output

The tool reads any file following the report schema, so it can score your
system's reports against the tweets they were produced from. Point
`--export-dir` at a directory laid out like the released data, with your reports
in place of the reference ones. This measures whether your system asserts more
than its input supports, which is a different question from how well it matches
the reference, and one the shared task metrics do not capture.
