# Crisis Situation Report Generation — Shared Task

<!-- TODO before release: task name, venue, dates, contact address, citation.
     Marked [TBD] throughout. Cell and document counts marked [VERIFY] should
     be checked against the final export before publishing. -->

Generate structured situation reports from crisis social media.

Given a set of posts sent during a crisis, produce a situation report: a
structured summary of what is known at that point in time, organized into
sections, with each statement labeled by how well the evidence supports it.

---

## What is in this release

**Training data: 10 crisis documents, 163 cells.** [VERIFY]

Each crisis is a separate fictional scenario. Each is divided into four
cumulative time windows, and each window is sampled several times, giving a set
of (tweets, report) pairs that vary in how much evidence they contain.

```
data/train/{crisis}/{crisis}.{window}.{replicate}.tweets.jsonl    input
data/train/{crisis}/{crisis}.{window}.{replicate}.report.json     target
```

**Development and test data are not yet released.** Two development documents
and six test documents are being prepared and will be published on the dates
below. They are new crises, distinct from the ten in this release, so nothing
in the training data anticipates them. Test inputs will be released without
reports; reports will be published after the submission deadline.

| | Documents | Released |
| --- | --- | --- |
| Train | 10 | Now |
| Development | 2 | [TBD] |
| Test | 6 | [TBD] |

---

## Quick start

```python
import json

def load_cell(stem):
    """Read one training pair."""
    records = [json.loads(l) for l in open(f"{stem}.tweets.jsonl")]
    crisis = next(r for r in records if r["record_type"] == "crisis")
    window = next(r for r in records if r["record_type"] == "window")
    tweets = [r for r in records if r["record_type"] == "tweet"]
    report = json.load(open(f"{stem}.report.json"))
    return crisis, window, tweets, report

crisis, window, tweets, report = load_cell(
    "data/train/volcano/volcano.W2.k1")

print(crisis["title"], "-", crisis["hazard"], "in", crisis["location"])
print(len(tweets), "tweets between", window["start"], "and", window["end"])
print(tweets[0]["text"])

for section in report["sections"]:
    for sub in section["subsections"]:
        for bullet in sub["bullets"]:
            print(f"[{bullet['confidence']:9s}] {bullet['id']}  {bullet['text']}")
```

Compare a `W1` report with the `W4` report for the same crisis. The difference
between them is the task.

---

## Documentation

Read in this order:

| File | Contents |
| --- | --- |
| `OVERVIEW.md` | The task, the terms used throughout, and what it tests. Start here. |
| `DATA_FORMAT.md` | File formats, section schema, confidence labels, submission layout. |
| `DERIVATION_RULES.md` | How the reference reports were produced from the tweets. |
| `TAXONOMY_GUIDE.md` | The event and entity categories underlying the reports. |
| `taxonomy.yaml` | The taxonomy in machine-readable form. |
| `DATASHEET.md` | Provenance, generation method, limitations, license. |

`DERIVATION_RULES.md` is the one most worth reading before building anything.
It explains why an early-window report is short, and why the same statement
carries different confidence labels in different windows.

---

## Rules

**Each pair must be processed independently.** A system must produce the report
for a cell using only that cell's tweets.

Cells from the same crisis overlap substantially: windows are cumulative, and
replicates are drawn from the same pool of posts. A system that reads several
cells together can recover information that no individual cell supports. That
is not a solution to the task.

**Submissions must include a short description of method** confirming that
cells were processed independently.

**External resources are permitted.** General-purpose models, tools and corpora
may be used. The crises are fictional, so no external source contains
information about them.

---

## Evaluation

Systems are scored against the reference reports on sections 3 to 11, using
text similarity and a bullet-level alignment, together with agreement on
confidence labels. Scores are averaged over replicates within a window, then
over windows within a crisis, then over crises.

Full detail, including the submission format, is in the evaluation guide
[TBD: released with the development data].

---

## Dates

| | |
| --- | --- |
| Training data released | [TBD] |
| Development data released | [TBD] |
| Test inputs released | [TBD] |
| Submission deadline | [TBD] |
| Results returned | [TBD] |

---

## License

MIT. See `LICENSE`.

This covers the synthetic corpus, the taxonomy, and the accompanying
documentation. Note that the real crisis corpora used to calibrate the
generation parameters are separately licensed and are not redistributed here;
see `DATASHEET.md`.

---

## Citation

[TBD]

## Contact

[TBD]
