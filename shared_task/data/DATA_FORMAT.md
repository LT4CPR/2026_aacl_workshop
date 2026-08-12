# Data format specification

This document defines the file formats used by the shared task. It covers the
input tweets, the situation report, the section schema, and the submission
layout.

---

## 1. Training pairs

The unit of the task is a **pair**: a set of tweets and the situation report
that should be produced from them.

```
{doc}.{window}.{replicate}.tweets.jsonl   input
{doc}.{window}.{replicate}.report.json    target
```

Both files of a pair share a stem, called a **cell identifier**. For example:

```
volcano.W2.k1.tweets.jsonl
volcano.W2.k1.report.json
```

The three components are:

| Component | Meaning |
| --- | --- |
| `{doc}` | The crisis document. Each document is one scenario with its own entities, locations and timeline. |
| `{window}` | A cumulative time window, `W1` to `W4`. `W1` is the earliest and shortest; each subsequent window extends the period from the start of the event, so `W1` tweets are a subset of `W2` tweets. |
| `{replicate}` | An identifier for the specific tweet sample: `k1`, `k2`, and so on. Replicates of the same window are independent samples drawn from that window's tweets, so they overlap heavily but are not identical. The number of replicates varies by document and window. The final window (`W4`) covers the complete event and has a single cell, `W4.k1`, containing all of that document's tweets. |

Directory layout:

```
data/
├── train/
│   └── {crisis}/
│       ├── {crisis}.W1.k1.tweets.jsonl
│       ├── {crisis}.W1.k1.report.json
│       └── ...
└── dev/
    └── {crisis}/
        └── ...
```

Test data follows the same layout under `data/test/`, released later, with
inputs only.

### Independence requirement

**Each pair must be processed independently.** A system must produce the report
for a cell using only that cell's tweets. Cells from the same document overlap
substantially, so a system that pools tweets or reports across cells can
reconstruct information that its own input does not support. This is not a
valid solution to the task.

Submissions must include a short description of method confirming that cells
were processed independently.

---

## 2. Input: tweets JSONL

UTF-8, one JSON object per line. The first two lines describe the crisis and
the reporting window; every subsequent line is a tweet. Each record carries a
`record_type` field.

```jsonl
{"record_type": "crisis", "title": "Eruption of Mount Vurren in the Sarnat Highlands", "hazard": "Volcanic eruption", "location": "Mount Vurren, Sarnat Highlands", "period": "Mar 3-8, 2026"}
{"record_type": "window", "cell_id": "volcano.W2.k1", "start": "2026-03-03T08:33:08Z", "end": "2026-03-04T23:33:08Z", "n_tweets": 198}
{"record_type": "tweet", "id": 1, "text": "Sarnat Volcano Observatory: reports of alert confirmed at Mount Vurren #MountVurren. Please avoid the area!!! #SarnatHighlands", "information_source": "Government", "timestamp": "Tue Mar 03 08:34:46 +0000 2026"}
{"record_type": "tweet", "id": 2, "text": "RT @NAA: Just heard warn at the volcano #SarnatHighlands. People are moving away!? #MountVurren #eruption http://ow.ly/qf9qjw", "information_source": "Eyewitness", "timestamp": "Tue Mar 03 08:39:57 +0000 2026"}
```

### `crisis` record

| Field | Description |
| --- | --- |
| `title` | The event, as a sentence-like name. |
| `hazard` | The hazard category. |
| `location` | Where the event occurs. |
| `period` | The span of the whole event, which may extend beyond this window. |

This is the context a system needs before reading any tweet: what kind of event
this is and where. It is given because a report cannot reasonably be produced
without it, and it is placed with the input rather than the target so that no
part of the answer has to be read in order to produce the answer.

Note that `period` describes the **whole event**, not this cell. The reporting
period for this cell is in the `window` record.

### `window` record

| Field | Description |
| --- | --- |
| `cell_id` | The cell identifier, matching the file name. |
| `start`, `end` | The reporting period, UTC ISO 8601. Nothing after `end` should be reported. |
| `n_tweets` | Number of tweet records that follow. |

### `tweet` records

| Field | Description |
| --- | --- |
| `id` | Integer, `1` to `N`, assigned in timestamp order. **IDs are local to the cell**: ID 1 in `volcano.W1.k1` and ID 1 in `volcano.W1.k2` are unrelated. |
| `text` | The tweet. May contain hashtags, `@` mentions, URLs, and a leading `RT @handle:` marker. |
| `information_source` | The source category of the account. See below. |
| `timestamp` | UTC, in the format `Tue Mar 03 08:34:46 +0000 2026`. |

### Information Source values

| Value | Meaning |
| --- | --- |
| `Government` | Official bodies: agencies, emergency services, public authorities. |
| `Media` | News organizations and journalists. |
| `Eyewitness` | Accounts making a direct sensory claim about what the author observed. |
| `NGOs` | Humanitarian and relief organizations. |
| `Outsiders` | Members of the public reacting, relaying or asking questions, without a direct sensory claim. |
| `Not labeled` | No source category assigned. This includes off-topic tweets. |

A proportion of tweets in every cell are **off-topic**: ordinary social media
content unrelated to the crisis. These are present by design and should not
contribute to the report.

## 3. Target: report JSON

```json
{
  "meta": { "schema_version": "1.2" },
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
              "text": "No deaths were attributed to the eruption at any stage of the response.",
              "confidence": "confirmed",
              "tweet_ids": [12, 47]
            }
          ]
        }
      ]
    }
  ]
}
```

### Fields

**`meta`** — the schema version only. Event identification and the reporting
window are given in the input file, not repeated here.

**`sections`** — a list of sections in ascending id order. A section that has
no reportable content in the window is omitted.

**`subsections`** — grouping within a section. Subsection ids are the section
id followed by a letter (`3a`, `3b`). Titles are drawn from the fixed
vocabulary in section 5 below.

**`bullets`** — the information items.

| Field | Description |
| --- | --- |
| `id` | `{subsection}.{n}`, for example `3a.1`. Numbering restarts within each subsection. |
| `text` | One reported claim, as a complete sentence. |
| `confidence` | The evidential status of the claim. See section 4. |
| `tweet_ids` | The tweets in this cell that support the claim, by their `id` in the input file. May be empty. |

**Evidence links.** `tweet_ids` records which tweets support a bullet. The ids
refer to the `id` field of tweet records in the same cell's input file, so they
are only meaningful within that cell.

Section 1 bullets carry no evidence links, because they synthesize across
several claims rather than reporting one. **Every bullet in sections 2 to 11
has at least one evidence link.**

Producing evidence links is part of the task: bullet alignment during
evaluation combines text similarity with overlap of the cited ids.

---

## 4. Confidence labels

Confidence is part of the task and is evaluated. It records how well the tweets
in the cell support the claim.

| Label | Use |
| --- | --- |
| `confirmed` | Corroborated by enough independent reports within the window. |
| `unconfirmed` | Reported but not sufficiently corroborated. Covers claims that are single-sourced, contradicted elsewhere, or stated as an intention that has not yet occurred. |

The distinction is **corroboration, not source type**. An official account
reporting something once does not make it confirmed, and a claim can be
confirmed on the strength of several non-official reports. This mirrors real
crisis reporting, where official sources are also wrong early on; several of the
documents contain official statements that are later corrected.

The same claim can hold different labels in different windows. A figure reported
by one account in an early window is `unconfirmed`; once corroborated in a later
window it becomes `confirmed`. Systems are expected to reflect this.

Across the released reports, roughly 74 percent of bullets are `confirmed` and
26 percent `unconfirmed`.

---

## 5. Section schema

Eleven sections. The underlying schema defines further sections for
cross-cutting analysis, but they are outside the scope of this task and do not
appear in the data.

| Id | Title | Scored | Content |
| --- | --- | --- | --- |
| 1 | Situation overview | No | See below. |
| 2 | Timeline | No | Chronological digest of the event. |
| **3** | **Casualties and human impact** | **Yes** | Deaths, injuries, missing persons, rescues, treatment and admissions. |
| **4** | **Infrastructure and service impact** | **Yes** | Damage, destruction, service disruptions, restoration progress. |
| **5** | **Displacement and movement** | **Yes** | Evacuations, displacement, returns, access constraints. |
| **6** | **Hazard assessment** | **Yes** | The state and behavior of the hazard itself. |
| **7** | **Response actions** | **Yes** | Operational response. Aid belongs in section 9, not here. |
| **8** | **Communication and information** | **Yes** | Warnings and alerts, information updates, corrections, requests for help. |
| **9** | **Aid and relief** | **Yes** | Aid provided, aid received and unmet needs, donations and financial transfers. |
| **10** | **Organizational and administrative activity** | **Yes** | Meetings and decisions, administrative and economic measures. |
| **11** | **Social and community response** | **Yes** | Social support, public sentiment. |


Reports contain sections 1 to 11. Only sections 3 to 11 are scored. Systems
should still produce sections 1 and 2, which are described below, but their
content does not affect the score.

### Section 1: situation overview

A standalone summary. A reader who sees only this section should understand the
situation. Four bullets, in this order:

1. What happened, where, and when.
2. Human impact: the operative casualty and displacement figures.
3. The principal cause or mechanism, if established.
4. The response and the current status.

Overview bullets synthesize across several claims, which is why they are not
scored in the same way as the atomic claims in sections 3 to 11.

### Subsection titles

Subsection titles come from a fixed vocabulary. Not every subsection appears in
every document.

| Section | Subsection titles |
| --- | --- |
| 3 | Fatalities; Injuries; Cases; Missing persons; Trapped persons; Rescued persons; Found persons; Treatment and admissions |
| 4 | Damage; Destruction; Service disruptions; Restoration progress |
| 5 | Evacuations; Displacement; Returns; Access constraints |
| 6 | Hazard assessment |
| 7 | Operational response |
| 8 | Warnings and alerts; Information updates; Requests for help |
| 9 | Aid provided and distributed; Aid received and needs coverage; Donations and financial transfers |
| 10 | Meetings and decisions; Administrative and economic measures |
| 11 | Social support; Public sentiment |

Subsection ids are assigned in order of appearance within the section, so the
same title may carry different ids in different documents. Alignment during
evaluation is by subsection, so producing the right grouping matters.

---

## 6. Submission format

One report per test cell, mirroring the released structure:

```
submission/{doc}/{doc}.{window}.{replicate}.report.json
```

Each file follows section 3 of this document. Submissions must also include:

- `methods.md` — a short description of the approach, confirming that cells
  were processed independently.

A cell for which no report is submitted is scored as absent, and coverage is
reported alongside the scores.

---

## 7. Notes on the data

**Off-topic tweets** are present in every cell and should not contribute to the
report.

**Corrections and rumours.** Some documents contain claims that circulate and
are later corrected by official sources. A report should reflect the corrected
position and, where relevant, record the correction in section 8.

**Figures change.** Casualty and impact figures are revised across windows, in
both directions. The operative figure for a window is the one supported by that
window's tweets, not the one that will eventually prove correct.

**Fictional content.** All crisis documents are fictional. Names of places,
organizations and people do not refer to real entities. Temporal and structural
properties of the corpora were calibrated against real annotated crisis
datasets.
