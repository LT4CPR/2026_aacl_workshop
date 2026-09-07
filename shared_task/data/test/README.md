# LT4CPR Shared Task — Test Data Release

## Overview

This package contains the **test inputs** for the LT4CPR shared task on generating structured situation reports from crisis-related social media.

For each test instance, participants receive a time-bounded and, in some cases, subsampled collection of synthetic social-media messages. The goal is to produce a structured situation report containing the information that can be supported by the messages in that instance.

**Important:** all crises, locations, people, organizations, and social-media messages in this dataset are fictional and synthetically generated for research purposes. The data do not describe real emergencies.

Reference reports for the test set are withheld and will be used by the organizers for evaluation.

---

## Task

**Input:** a JSONL file containing crisis/window metadata followed by social-media messages.

**Output:** one structured situation report in JSON format for every input file.

A system report should:

- summarize important information supported by the input messages;
- organize information under the official situation-report sections;
- distinguish **confirmed** from **unconfirmed** information;
- cite the input message IDs that support each generated bullet;
- avoid introducing facts that are not supported by the current test instance.

Each test instance must be processed independently. In particular, information from another window, replicate, crisis, external reconstruction of the hidden reference, or a later point in the same crisis must not be used as if it were present in the current input.

---

## Package Structure

The test package is organized as:

```text
test/
├── collapse/
│   └── *.tweets.jsonl
├── damsafety/
│   └── *.tweets.jsonl
├── heatwave/
│   └── *.tweets.jsonl
├── indfire/
│   └── *.tweets.jsonl
├── landslide/
│   └── *.tweets.jsonl
└── tornado/
    └── *.tweets.jsonl
```

The current release contains **117 public test instances**:

| Crisis | Test instances |
|---|---:|
| `collapse` | 19 |
| `damsafety` | 19 |
| `heatwave` | 13 |
| `indfire` | 16 |
| `landslide` | 28 |
| `tornado` | 22 |
| **Total** | **117** |

Each `.tweets.jsonl` file is one independent system input and requires one corresponding system-output report.

---

## Input Format

Each test instance is a JSON Lines (`.jsonl`) file.

The file begins with:

1. one **crisis metadata** record;
2. one **window metadata** record;
3. one or more **tweet/message** records.

The participant-facing message records have the same interface as the released training and development data.

A message record has the following core fields:

```json
{
  "id": 42,
  "text": "Example crisis-related message.",
  "information_source": "Media",
  "timestamp": "Tue Jul 08 19:57:44 +0000 2025"
}
```

### `id`

A positive integer identifying the message **within the current test instance**.

IDs are local to a cell. Do not assume that message ID `42` in one file refers to the same underlying message as ID `42` in another file.

Use these integer IDs when filling the `tweet_ids` evidence field in your system report.

### `text`

The social-media message visible to the system.

### `information_source`

A coarse source category. Values follow the same vocabulary used in the training/development release, including categories such as:

- `Government`
- `Media`
- `Eyewitness`
- `NGOs`
- `Outsiders`
- `Not labeled`

### `timestamp`

The timestamp associated with the message.

Systems should respect the temporal scope of the current input. A test instance may represent only an earlier portion of a crisis, so later developments must not be assumed.

---

## Expected System Output

For **each submitted system**, produce one JSON report for every `.tweets.jsonl` input file.

The participant-facing report format follows schema version `1.2` and contains:

```text
meta
└── schema_version

sections
└── section
    └── subsection
        └── bullet
            ├── id
            ├── text
            ├── confidence
            └── tweet_ids
```

The participant-facing task uses **Sections 1–11 only**.

### Report Sections

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

Sections 12–15 used by the organizers' internal representation are **not part of the participant output**.

Use the section/subsection organization demonstrated in the released training reports and official situation-report template. Sections or subsections for which your system produces no content may be omitted unless the final submission validator distributed by the organizers specifies otherwise.

---

## Output Example

A minimal system output may look like:

```json
{
  "meta": {
    "schema_version": "1.2"
  },
  "sections": [
    {
      "id": "3",
      "title": "Casualties and human impact",
      "subsections": [
        {
          "id": "3b",
          "title": "Injuries",
          "bullets": [
            {
              "id": "3b.1",
              "text": "Thirty-eight people were injured in Estenwick.",
              "confidence": "confirmed",
              "tweet_ids": [17, 22, 31]
            }
          ]
        }
      ]
    },
    {
      "id": "4",
      "title": "Infrastructure and service impact",
      "subsections": [
        {
          "id": "4b",
          "title": "Service disruption",
          "bullets": [
            {
              "id": "4b.1",
              "text": "Service at the school was disrupted in Estenwick.",
              "confidence": "unconfirmed",
              "tweet_ids": [44]
            }
          ]
        }
      ]
    }
  ]
}
```

This example illustrates the format only. The statements and IDs above are not reference answers for any test instance.

---

## Bullet Format

Every generated bullet must contain:

```json
{
  "id": "3b.1",
  "text": "A concise factual statement.",
  "confidence": "confirmed",
  "tweet_ids": [17, 22]
}
```

### `id`

A unique bullet identifier within the report.

Use IDs consistent with the report hierarchy, for example:

```text
3b.1
3b.2
3b.3
```

Number system-generated bullets sequentially within each subsection. Do **not** attempt to guess hidden reference-report bullet IDs; the ID identifies the bullet in your own submitted report.

### `text`

A natural-language situation-report statement.

Prefer one coherent claim or a tightly related group of facts per bullet. Reports should consolidate redundant messages without adding unsupported details.

### `confidence`

Exactly one of:

```text
confirmed
unconfirmed
```

Do not submit internal labels such as `potential`, `absent`, `announced`, or `background`.

A negative statement such as "No fatalities were reported" is represented in the **text itself**. Its `confidence` indicates confidence in that statement; it does not reverse the statement's polarity.

### `tweet_ids`

A JSON array of integer message IDs from the **same input file** that support the bullet.

Example:

```json
"tweet_ids": [12, 18, 24]
```

Requirements:

- every cited ID must exist in the corresponding `.tweets.jsonl` file;
- do not cite IDs from another cell;
- do not cite internal or synthetic IDs such as `SYN_000123`;
- citations should support the complete factual content of the bullet;
- duplicate IDs should not be included;
- factual bullets should normally include at least one supporting message.

Evidence citations are part of the required structured output. Details of how citation quality contributes to the official score may be specified separately in the evaluation documentation.

---

## File Naming

For every input file:

```text
<cell>.tweets.jsonl
```

each submitted system must produce one report named:

```text
<cell>.report.json
```

For example, given:

```text
test/tornado/tornado.W2.k3.tweets.jsonl
```

a system with ID `retrieval-llm` should place its output at:

```text
<team_id>/systems/retrieval-llm/test/tornado/tornado.W2.k3.report.json
```

Keep the crisis directory and cell stem unchanged. Do **not** add the team name or system name to individual report filenames; team and system identity are represented by the enclosing directories and the submission manifest.

---

## Team and System Submission Structure

Each participating team submits **one ZIP archive**. The ZIP represents the team's complete shared-task submission and may contain outputs from one or more systems.

Each team must have:

- a human-readable **team name**;
- a machine-readable **team ID**;
- one or more submitted systems;
- a human-readable name and machine-readable ID for each system;
- exactly one system designated as the team's **primary system**.

Recommended machine-readable IDs use only lowercase ASCII letters, digits, hyphens, and underscores, and should match:

```text
[a-z0-9][a-z0-9_-]*
```

Examples:

```text
Team name: UW CrisisNLP
Team ID:   uw-crisisnlp

System name: Retrieval + LLM
System ID:   retrieval-llm
```

The human-readable name may contain spaces and normal punctuation. The machine-readable ID is used in directory names and by the submission validator.

---

## `submission.json`

Every team ZIP must contain a top-level `submission.json` manifest.

Example:

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

### Team fields

`team.id`

- required;
- must be a machine-safe team identifier;
- should match the top-level team directory name.

`team.name`

- required;
- human-readable team name used for organizer records and result presentation.

### System fields

Each object in `systems` must contain:

- `id`: unique machine-readable system ID within the team;
- `name`: human-readable system name;
- `primary`: Boolean indicating whether this is the team's primary submitted system.

Exactly **one** system must have:

```json
"primary": true
```

The primary system is the team's designated main run for the official team-level comparison. Additional systems may be submitted for alternative approaches, ablations, or supplementary analysis.

Detailed descriptions of models, prompts, APIs, external resources, retrieval sources, and human intervention do not need to be stored in `submission.json`; these should be documented according to the shared-task system-description and participation requirements.

The systems declared in `submission.json` must match the directories under `systems/` exactly:

- every declared system must have one directory;
- undeclared system directories are not allowed;
- system IDs must be unique within the team.

---

## Submission Package

The required archive structure is:

```text
<team_id>.zip
└── <team_id>/
    ├── submission.json
    └── systems/
        ├── <system_id_1>/
        │       ├── collapse/
        │       │   └── *.report.json
        │       ├── damsafety/
        │       │   └── *.report.json
        │       ├── heatwave/
        │       │   └── *.report.json
        │       ├── indfire/
        │       │   └── *.report.json
        │       ├── landslide/
        │       │   └── *.report.json
        │       └── tornado/
        │           └── *.report.json
        │
        └── <system_id_2>/
                ├── collapse/
                ├── damsafety/
                ├── heatwave/
                ├── indfire/
                ├── landslide/
                └── tornado/
```

For example:

```text
uw-crisisnlp.zip
└── uw-crisisnlp/
    ├── submission.json
    └── systems/
        ├── retrieval-llm/
        │       ├── collapse/
        │       ├── damsafety/
        │       ├── heatwave/
        │       ├── indfire/
        │       ├── landslide/
        │       └── tornado/
        └── zero-shot-llm/
                ├── collapse/
                ├── damsafety/
                ├── heatwave/
                ├── indfire/
                ├── landslide/
                └── tornado/
```

Each submitted system is a **complete run** and must contain exactly one report for each of the **117 public test inputs**.

Therefore:

```text
1 submitted system  = 117 report files
2 submitted systems = 234 report files
3 submitted systems = 351 report files
```

Systems must not submit only differences relative to another system, share report files through links, or omit cells because another submitted system contains them. Every system directory must be independently complete.

Do not include:

- the original `.tweets.jsonl` files;
- training or development data;
- model checkpoints;
- source code;
- logs;
- prompts;
- cached API responses;
- organizer/internal metadata;
- directories that are not declared in `submission.json`.

Unless the submission platform explicitly requests a different archive name, use:

```text
<team_id>.zip
```

---


## Submission Validator

Before uploading your team submission, run the official submission validator:

```text
tools/other_tools/validate_submission.py
```

The validator checks the team-level ZIP structure, `submission.json`, declared
systems, report-file coverage, report JSON structure, section/bullet hierarchy,
confidence labels, and evidence tweet IDs.

Run it from the root of the shared-task repository:

```bash
python3 tools/other_tools/validate_submission.py \
    --submission path/to/<team_id>.zip \
    --test-data data/test
```

If you are validating against the released test ZIP directly instead of an
extracted `data/test/` directory, pass the ZIP path:

```bash
python3 tools/other_tools/validate_submission.py \
    --submission path/to/<team_id>.zip \
    --test-data path/to/test.zip
```

A valid submission prints:

```text
VALID — submission passed all checks against 117 test cells.
```

The validator uses the released test data to derive the exact expected cell
inventory and valid tweet IDs. This means it checks more than the total number
of files: it verifies that every expected test cell is present for every
declared system and that every cited `tweet_id` actually occurs in the
corresponding input file.

The validator checks **submission format and referential integrity**. Passing
validation does not mean that a generated statement is factually correct or
supported by its cited tweets; semantic quality is evaluated separately.

Exit codes are:

| Exit code | Meaning |
| ---: | --- |
| `0` | Submission is valid |
| `1` | Submission is invalid |
| `2` | Validator/configuration error |

Participants are strongly encouraged to run the validator immediately before
submission. The version distributed with the shared-task repository should be
treated as authoritative if it differs from an older local copy.

---

## Submission Checklist

Before uploading, run `tools/other_tools/validate_submission.py` and verify that:

1. the ZIP contains exactly one top-level directory named `<team_id>/`;
2. `<team_id>/submission.json` exists and is valid UTF-8 JSON;
3. `submission_format_version` is `"1.0"`;
4. `team.id` matches the top-level directory name;
5. `team.name` is non-empty;
6. every system ID is unique and machine-safe;
7. the directories under `<team_id>/systems/` exactly match the systems declared in `submission.json`;
8. exactly one declared system has `"primary": true`;
9. **each system contains exactly 117 `.report.json` files**;
10. every test input has exactly one matching report within each system;
11. every report is valid UTF-8 JSON;
12. `meta.schema_version` is `"1.2"`;
13. only Sections 1–11 are used;
14. every bullet contains `id`, `text`, `confidence`, and `tweet_ids`;
15. every `confidence` value is either `confirmed` or `unconfirmed`;
16. every `tweet_ids` value is a JSON array of integer IDs from the corresponding input file;
17. no internal identifiers or organizer metadata appear in the output;
18. every system preserves the required `test/<crisis>/<cell>.report.json` structure;
19. no undeclared system directories or extra report files are present.

Use the official submission validator when it is released. A locally valid JSON file is not necessarily a schema-valid shared-task submission.

---

## Relationship to Training and Development Data

The test inputs use the same participant-facing input interface as the released training and development data.

Training/development instances contain paired reference reports that demonstrate:

- the report hierarchy;
- section and subsection organization;
- bullet construction;
- binary confidence labels;
- evidence citation with integer message IDs.

Test reference reports are withheld.

Participants should use the released training/development reports and official template as the authoritative examples for output structure.

---

## Evaluation

Systems are expected to generate reports that are:

- **faithful** to the provided messages;
- **informative**, covering important supported developments;
- **well organized** under the task report structure;
- **non-redundant**;
- appropriate in their handling of **uncertainty and negation**;
- grounded in the supplied evidence.

The organizers will evaluate submissions against withheld reference reports. Exact metric definitions, ranking rules, and the treatment of evidence citations are provided separately in the official evaluation documentation.

Do not assume that two test cells from the same crisis have the same target report. Windows and sampled message subsets differ, so the supportable report can differ across cells.

---

## Data Integrity and Reproducibility

The test package was generated with the same participant-facing cell/export interface used for the training/development release. Test-cell membership and participant message IDs are fixed independently of later text-only processing.

Participants should treat the contents of each released `.tweets.jsonl` file as immutable task input.

---

## Responsible Use

This benchmark is intended for research on crisis informatics, summarization, information extraction, evidence-grounded generation, and evaluation.

The dataset is synthetic and depicts fictional emergencies. It must not be represented as documentation of real events.

Automated situation-report generation is a high-stakes application. Benchmark performance should not be interpreted as evidence that a system is safe for deployment in real emergency-response settings without further validation, human oversight, and appropriate operational safeguards.

---

## Questions

Please use the official LT4CPR shared-task contact channel for questions about:

- the data;
- the output schema;
- submission validation;
- evaluation;
- participation rules.

If a later task announcement or official validator conflicts with this README, the **latest official shared-task instructions take precedence**.
