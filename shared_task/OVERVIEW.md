
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

This is a summarisation task with two properties that distinguish it from
ordinary summarisation.

**The output is structured.** A report is not free text. It is a set of
sections, each containing short factual statements, each labelled with how well
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

**Document.** One crisis scenario, with its own places, organisations, hazard
and timeline. This dataset contains ten. A document is the largest unit: no
information carries across documents.

**Window.** A period of time from the start of the event, labelled `W1` to
`W4`. Windows are **cumulative**: `W2` covers everything `W1` covers and more.
`W1` is the opening hours, when little is confirmed; `W4` covers the complete
event. Window boundaries were chosen where the reported situation changed most,
so they differ between documents.

**Replicate.** One sample of tweets from a window, labelled `k1`, `k2`, and so
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
it: `confirmed`, `potential`, `announced`, or `absent`.

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

Corpus scale, across the ten documents:

| | |
| --- | --- |
| Documents | 10 |
| Cells | 163 |
| Tweets per cell | 22 to 997 |
| Bullets per report | 8 to 93, median 31 |

Cells vary in size by design. The smallest are early windows where a system has
little to work with; the largest cover a complete event.

---

## 4. The data is synthetic

Every crisis in this dataset is fictional. The places, organisations and people
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
judgement. This is described in **`DERIVATION_RULES.md`**.

**Fictional content prevents memorisation.** A model that has read about a real
event can reproduce facts about it without reading the input. Fictional events
make that impossible: the only source of information is the tweets provided.

**The statistics are real.** Timing, source mix, hashtag and retweet rates,
orthography and off-topic proportion were calibrated against annotated corpora
from real events, so the posts behave like real crisis streams even though
their content is invented.

Corpus generation is documented separately; systems do not need to know how it
works.

---

## 5. What the task tests

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

**Recognising superseded guidance.** In one document an evacuation radius
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

## 6. Rules

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

## 7. Evaluation

Systems are scored against the reference reports.

**Scope.** Reports contain sections 1 to 11. Sections 3 to 11 — those
containing atomic factual claims — are scored. Sections 1 and 2 (overview and
timeline) synthesise across claims and are not scored, but systems should still
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

## 8. Documents in this package

| File | Contents |
| --- | --- |
| `OVERVIEW.md` | This document. |
| `DATA_FORMAT.md` | File formats, section schema, confidence labels, submission layout. |
| `DERIVATION_RULES.md` | How reference reports were produced from tweets. |
| `TAXONOMY_GUIDE.md` | The event and entity categories underlying the reports. |
| `taxonomy.yaml` | The taxonomy in machine-readable form. |

---

## 9. Where to start

1. Read `DATA_FORMAT.md` and open one pair — the input file and its report side
   by side.
2. Read `DERIVATION_RULES.md`. It explains why an early-window report is short
   and why the same claim carries different confidence labels in different
   windows. This is the single most useful thing to understand before building
   anything.
3. Compare `W1` and `W4` reports for the same document. The difference between
   them is the task.
