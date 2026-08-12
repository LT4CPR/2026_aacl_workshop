# Task overview

## Generating situation reports from crisis social media

---

## 1. What the task is

Given a set of social media posts sent during a crisis, produce a **situation
report**: a structured summary of what is known about the event at that point
in time.

```
tweets from a crisis  ->  [ your system ]  ->  situation report
```

This is a summarization task with two properties that distinguish it from
ordinary summarization.

**The output is structured.** A report is not free text. It is a set of
sections, each containing short factual statements, each labeled with how well
the evidence supports it.

**The input is partial.** Each set of tweets covers a bounded period, often
early in an event when little is confirmed. A correct report says what those
tweets support and no more. Reporting something true of the event but not
present in the input is an error.

---

## 2. Terms

These terms are used throughout the task materials.

**Situation report (sitrep).** A structured summary of a crisis at a point in
time, used in emergency management to give responders a shared picture of what
is known. Real sitreps are produced by hand under time pressure; this task asks
whether they can be produced automatically from social media.

**Document.** One crisis scenario, with its own places, organizations, hazard
and timeline. This release contains ten: eight for training and two for
development. A document is the largest unit: no information carries across
documents.

**Window.** A period of time from the start of the event, labeled `W1` to
`W4`. Windows are **cumulative**: `W2` covers everything `W1` covers and more.
`W1` is the opening hours, when little is confirmed; `W4` covers the complete
event. Window boundaries were chosen where the reported situation changed most,
so they differ between documents.

**Replicate.** One sample of tweets from a window, labeled `k1`, `k2`, and so
on. Replicates of the same window are drawn independently, so they overlap
substantially but are not identical. They exist because a system should not
depend on receiving one particular set of posts.

**Cell.** One (window, replicate) combination for one document: the unit of the
task. A cell is identified by `{document}.{window}.{replicate}`, for example
`volcano.W2.k1`.

**Pair.** A cell's tweets together with its reference report. Pairs are what
you train on.

**Bullet.** A single statement in a report. One claim, one sentence, together
with the ids of the tweets supporting it.

**Section and subsection.** Bullets are grouped into subsections, and
subsections into numbered sections by topic — casualties, infrastructure,
displacement, and so on. The section schema is fixed and given in the data
format specification.

**Confidence.** A label on each bullet recording how well the tweets support
it: `confirmed` when corroborated by enough independent reports in the window,
`unconfirmed` otherwise.

**Off-topic tweets.** Ordinary social media content unrelated to the crisis,
present in every cell. Real crisis streams contain them and a system has to
ignore them.

**Reference report.** The report provided as the target for a pair. Also called
the gold report.

---

## 3. What you receive

Each pair is two files:

```
volcano.W2.k1.tweets.jsonl     input
volcano.W2.k1.report.json      target
```

The input file opens with two records describing the crisis and the reporting
window, followed by one record per tweet with its text, source category and
timestamp. The target is the structured report.

Formats are specified in full in **`DATA_FORMAT.md`**.

Scale of this release:

| | Train | Development |
| --- | --- | --- |
| Documents | 8 | 2 |
| Cells | 140 | 23 |
| Tweets per cell | 22 to 993 | 74 to 997 |
| Bullets per report | 8 to 85, median 27 | 17 to 93, median 58 |

Cells vary in size by design. The smallest are early windows where a system has
little to work with; the largest cover a complete event.

---

## 4. Data splits

The data is released in stages.

| Split | Documents | Cells | Released | Contents |
| --- | --- | --- | --- | --- |
| Train | 8 | 140 | August 7, 2026 | Tweets and reference reports |
| Development | 2 | 23 | August 7, 2026 | Tweets and reference reports |
| Test | New crises | -- | September 1, 2026 | Tweets only; reports published after the submission deadline |

Every document is a separate crisis. The two development documents are
distinct crises from the eight training ones, and the test documents are
distinct again from both. Nothing in one split describes another, and no
external source contains information about any of them, since all crises are
fictional.

Development data is for tuning and model selection. Fitting on it defeats its
purpose.

Consult the task page for the current schedule:
<https://lt4cpr.github.io/aacl2026-workshop-LT4CPR/shared-task.html>

---

## 5. The data is synthetic

Every crisis in this dataset is fictional. The places, organizations and people
do not exist.

This is a deliberate choice, and the reasons matter for how the task should be
approached.

**Real annotated crisis data is scarce and hard to release.** Producing a
reference sitrep for a real event requires expert annotation over thousands of
posts, and platform terms often prevent redistributing the posts themselves.

**Synthetic data makes the reference verifiable.** Each tweet in this dataset
was generated from a record of exactly what it reports. The reference report is
then derived from those records by fixed rules, so the relationship between a
set of tweets and its report is exact rather than a matter of annotator
judgment. This is described in **`DERIVATION_RULES.md`**.

**Fictional content prevents memorization.** A model that has read about a real
event can reproduce facts about it without reading the input. Fictional events
make that impossible: the only source of information is the tweets provided.

**The statistics are real.** Timing, source mix, hashtag and retweet rates,
orthography and off-topic proportion were calibrated against annotated corpora
from real events, so the posts behave like real crisis streams even though
their content is invented.

Corpus generation is documented separately; systems do not need to know how it
works.

---

## 6. What the task tests

Each document was built around a specific difficulty. Together they test
capabilities a usable system would need.

**Reporting only what is supported.** One document has a crisis with no
fatalities. A system that reports casualties because crises usually have them
is measurably wrong.

**Tracking figures that change.** Casualty figures are revised as events
develop, in both directions. Some rise as reports accumulate; in one document a
suspected case count is revised sharply downward once laboratory results
arrive. The correct figure for a window is the one that window's tweets
support, not the highest seen.

**Distinguishing categories that must not be summed.** In one document,
passengers move between rescued, unaccounted for, and confirmed dead as a
search progresses. Missing is not dead. A system that adds these together, or
treats one as the other, is wrong.

**Recognizing superseded guidance.** In one document an evacuation radius
changes four times. Earlier instructions become incorrect, not merely
incomplete. The report must state what is operative now.

**Following a staged official status.** In one document an alert level moves
through named stages and back down. Only one level is in force at a time.

**Handling corrections and rumours.** Claims circulate and are corrected by
officials. Inflated casualty figures appear in some documents and are publicly
denied.

**Working from thin evidence.** In one document the event lasts minutes and
officials are silent for the first two hours, so the earliest windows contain
almost nothing but eyewitness accounts.

**Reporting before the event.** In two documents the earliest windows precede
the main event, covering the forecast or warning phase.

---

## 7. A property of the reference reports

A reference statement is kept when the cell contains a tweet reporting the event
it describes. That guarantees the event is present. It does not guarantee that
the tweets state every detail the statement carries.

Surface realization preserves the event and the entities involved, but not
always the specific values attached to them. A statement recording that an alert
level moved from Green to Yellow may cite tweets that report only a tremor at
the summit; a statement that trains resumed on a reduced, free timetable may
cite a tweet saying services are coming back online. Numeric figures are stated
in the tweets that evidence them; named categorical values are not always.

Two consequences are worth planning for.

**Some statements cannot be reproduced from the input.** A system that reports
only what the tweets support will fall short of the reference on those
statements. This is a property of the data, not a failure of the system, and it
applies equally to every participant.

**Do not treat it as licence to elaborate.** The gap is narrow and specific.
Inventing plausible detail is penalised far more often than it is rewarded,
because most statements are supported and several documents are built
specifically to detect fabrication.

An audit tool (`tools/other_tools/audit_faithfulness.py`) is included so this
can be measured rather than guessed at. It decomposes each statement into atomic claims and
scores each against the cited tweets by entailment.

---

## 8. Rules

### Each cell must be processed independently

A system must produce the report for a cell using **only that cell's tweets**.

Cells from the same document overlap heavily: windows are cumulative and
replicates are drawn from the same pool. A system that reads several cells
together can therefore recover information that any individual cell does not
support, and would appear to perform well while doing something the task does
not ask for.

Submissions must include a short description of method confirming that cells
were processed independently.

### External resources

General-purpose models, tools and corpora may be used. The crises are
fictional, so no external source contains information about them.

---

## 9. Evaluation

Systems are scored against the reference reports.

**Scope.** Reports contain sections 1 to 11. Sections 3 to 11 — those
containing atomic factual claims — are scored. Sections 1 and 2 (overview and
timeline) synthesize across claims and are not scored, but systems should still
produce them.

**Metrics.** Text similarity against the reference, and a bullet-level
alignment that matches produced bullets to reference bullets within
subsections. The alignment combines text similarity with agreement on which
tweets a bullet cites. Confidence labels are also scored.

**Aggregation.** Scores are averaged over replicates within a window, then over
windows within a document, then over documents. Documents are the independent
unit: replicates of the same window are near-identical by construction, so
treating them as independent observations would overstate confidence in any
result.

Full detail is in the evaluation guide.

---

## 10. Documents in this package

| File | Contents |
| --- | --- |
| `README.md` | Release contents, quick start, dates and contact. |
| `OVERVIEW.md` | This document. |
| `DATA_FORMAT.md` | File formats, section schema, confidence labels, submission layout. |
| `DERIVATION_RULES.md` | How reference reports were produced from tweets. |
| `TAXONOMY_GUIDE.md` | The event and entity categories underlying the reports. |
| `taxonomy.yaml` | The taxonomy in machine-readable form. |
| `tools/other_tools/audit_faithfulness.py` | Measure how well each reference statement is supported by its cited tweets. |
| `DATASHEET.md` | Provenance, generation method, limitations, license. |

---

## 11. Where to start

1. Read `DATA_FORMAT.md` and open one pair — the input file and its report side
   by side.
2. Read `DERIVATION_RULES.md`. It explains why an early-window report is short
   and why the same claim carries different confidence labels in different
   windows. This is the single most useful thing to understand before building
   anything.
3. Compare `W1` and `W4` reports for the same document. The difference between
   them is the task.
