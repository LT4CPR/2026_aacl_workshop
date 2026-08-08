# LT4CPR Shared Task on Automatic Situation Report Generation

First Workshop on Language Technologies for Crisis Preparedness and Response
(LT4CPR), AACL-IJCNLP 2026 — Hengqin, Zhuhai, China and online, November 9, 2026.

Task page: <https://lt4cpr.github.io/aacl2026-workshop-LT4CPR/shared-task.html>

Generate structured situation reports from crisis social media.

Given a set of posts sent during a crisis, produce a situation report: a
structured summary of what is known at that point in time, organized into
sections, with each statement labeled by how well the evidence supports it.

---

## What is in this release

**Training data: 10 crisis documents, 163 cells.**

Each crisis is a separate fictional scenario. Each is divided into four
cumulative time windows, and each window is sampled several times, giving a set
of (tweets, report) pairs that vary in how much evidence they contain.

```
data/train/{crisis}/{crisis}.{window}.{replicate}.tweets.jsonl    input
data/train/{crisis}/{crisis}.{window}.{replicate}.report.json     target
```

**Development and test data are released later.** Both consist of new crises,
distinct from the ten in this release, so nothing in the training data
anticipates them. Test inputs are released without reference reports; the
reports are published after the submission deadline.

| | Released |
| --- | --- |
| Train | August 7, 2026 |
| Development | To be announced |
| Test | September 1, 2026 |

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

## Viewing the data

Two tools are included.

**`view_cell.py`** renders one pair as a self-contained HTML page: the tweets
on the left, the reference report on the right. Selecting a statement
illuminates the tweets that support it; selecting a tweet illuminates the
statements it supports. That relationship is the task, and it is the fastest
way to understand what a correct report looks like.

```bash
python3 view_cell.py data/train/volcano/volcano.W2.k1 --open
```

**`show_tweets.py`** prints tweets in the terminal, with filtering and a
summary of the stream.

```bash
python3 show_tweets.py data/train/volcano/volcano.W1.k1.tweets.jsonl
python3 show_tweets.py data/train/ferry/ferry.W2.k1.tweets.jsonl --stats
python3 show_tweets.py data/train/ferry/ferry.W2.k1.tweets.jsonl -s Government -g "rescued|missing"
```

Both are plain Python with no dependencies.

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
| `view_cell.py` | Render a pair as an HTML page. |
| `show_tweets.py` | Inspect tweets in the terminal. |

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

Evaluation metric scripts, definitions, baseline code and submission format
validation are released between August 7 and September 1, 2026. See the task
page for the current status.

---

## Dates

All deadlines are 11:59 p.m. Anywhere on Earth. Dates are tentative; consult
the task page for updates.

| | |
| --- | --- |
| Training data release | August 7, 2026 |
| Evaluation resources and baselines | August 7 – September 1, 2026 |
| Participant registration deadline | August 25, 2026 |
| Test data release | September 1, 2026 |
| System output submission deadline | September 7, 2026 |
| System description paper deadline | September 15, 2026 |
| Notification of acceptance | October 1, 2026 |
| Camera-ready papers due | October 10, 2026 |
| LT4CPR workshop | November 9, 2026 |

---

## License

MIT. See `LICENSE`.

This covers the synthetic corpus, the taxonomy, and the accompanying
documentation. Note that the real crisis corpora used to calibrate the
generation parameters are separately licensed and are not redistributed here;
see `DATASHEET.md`.

---

## Citation

A shared task overview paper will be published; until then cite the task page.

## Contact

<lt4cpr.sharedtask@gmail.com>

Questions about the data or the task should go to this address. Updates are
posted on the task page.

---

This material is based upon work supported by the National Science Foundation
under Grant Nos. 2346334 and 2346335.
