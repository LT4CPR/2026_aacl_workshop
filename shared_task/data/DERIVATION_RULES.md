# How the reports were derived

Every report in this dataset was produced mechanically from its tweets by a
fixed set of rules. No report was written by hand for a specific window, and no
model wrote them. This document states the rules, because they determine what a
correct report looks like and why reports for the same document differ across
windows.

The rules are released so that participants can see exactly what relationship
holds between a set of tweets and its report. Reproducing the rules is not the
task; producing the report from the tweets is.

---

## 1. Where reports come from

Each crisis document has one **full report**, written first, covering the whole
event. Every released report is derived from that full report by asking: given
only this cell's tweets, which of these items are supported, and how strongly?

```
full report  +  cell tweets  ->  derivation rules  ->  cell report
```

Two consequences follow, and both matter.

**Bullet text is taken verbatim from the full report.** The rules select, drop
and relabel items; they do not rewrite text and do not invent items. A bullet
that appears in a W1 report appears identically in the W4 report if it survives
that far.



**A cell report is not a summary of the whole event.** It is the report a
careful analyst would produce knowing only what those tweets say. Content the
tweets do not support is absent, even when it is true of the event as a whole.

---

## 2. The rules

### R1 — Survival requires evidence

A bullet survives if at least one tweet in the cell reports the underlying
event. Reposts count as evidence: a retweet of a report is still a report of
it.

A bullet whose supporting tweets are all absent from the cell is dropped
entirely, not weakened. This is the main reason early windows are short.

### R2 — Confidence follows evidence density

A bullet labeled `confirmed` or `announced` in the full report is downgraded
to `potential` when the cell contains fewer supporting tweets than a threshold
based on how well the item was supported overall.

The threshold is `max(2, ceil(0.34 x full-report support))`. In practice: an
item supported by a single tweet in this cell is rarely `confirmed`, even when
it is well corroborated later in the event.

Two cases do not downgrade:

- `potential` stays `potential`. It cannot weaken further.
- `absent` bullets, which record information gaps, survive only while the
  evidence establishing the gap survives.

### R3 — Evolving figures resolve to the latest supported one

Each announcement of a figure is a separate bullet in the full report. A death
toll that moves from 4 to 9 to 18 is three bullets, each tied to the tweets
that announced it.

Losing the evidence for a later figure drops that bullet, and the latest
surviving figure becomes the operative one. Summary figures elsewhere in the
report are updated to match.

This is why a report may state a lower figure than the event eventually
reached. The lower figure is correct for that window.

### R3a — No figures the window has not reached

Some bullets are analytical and are not tied to specific tweets. If such a
bullet cites a figure larger than any figure the cell's tweets support, it is
dropped as anachronistic.

A window whose tweets report no figures at all cannot support any bullet citing
a casualty figure.

### R3c — No dates beyond the window

Any bullet citing an explicit calendar date after the window end is dropped. A
report cannot narrate days that have not happened.

### R3d — No retrospective framing in partial windows

In any window short of the full event, evidence-free bullets containing strong
retrospective markers are dropped: *final*, *was later*, *superseded by*,
*culminating in*, *occurred after*.

Such phrasing presupposes a vantage point after the event. Bullets that record
an information gap are exempt, since noting that something remains unknown is
appropriate mid-event.

### R4 — Evidence is remapped and structure is pruned

Each surviving bullet's evidence links are rewritten to refer to the tweets
present in this cell, using the ids from the cell's input file. Links to tweets
outside the cell are removed.

Subsections left with no bullets are removed, and sections left with no
subsections are removed. A section absent from a report means the cell's tweets
support nothing in it.

Absence is meaningful. A system that produces content for a section the gold
omits is reporting something the tweets do not support.

### R5 — Window metadata

`meta.window` records the period the cell covers. Nothing occurring after
`window.end` should be reported.

---

## 3. What this means when building a system

**Report what the tweets support, not what the event turned out to be.** The
rules are strict about this, and the reference reports for early windows are
correspondingly sparse. A system that fills gaps with plausible crisis
narrative will be penalized, because the reference does not contain that
content.

**Calibrate confidence to corroboration.** A single unattributed report is
`potential`. The same claim, repeated by an official account and a news
account, is `confirmed`. Because R2 is threshold-based, this shifts across
windows for the same claim.

**Track figures rather than accumulating them.** The operative figure is the
latest one the window supports, not the maximum seen. Some documents revise
figures downward, and some distinguish categories that must not be summed.

**Omit sections with no support.** Producing a section the reference omits
costs precision.

**Watch the window boundary.** Nothing after `window.end`, and no retrospective
framing in a window short of the full event.

---

## 4. Known limitations

Stated because they affect the reference reports participants train on.

**Figure extraction is heuristic.** R3 and R3a locate figures with pattern
matching. Word-numbers and unusual phrasings can be missed, so a small number
of figure-bearing bullets may survive or drop incorrectly.

**The retrospective marker list is fixed.** R3d uses a fixed set of phrases.
Retrospective framing expressed differently is not caught.

**Bullets can be partly supported.** R1 keeps a bullet when at least one of its
supporting tweets is present. A bullet citing several tweets can therefore
survive on a subset of them, and assert slightly more than the cell strictly
establishes. This is most common in early windows.

**Section 1 is inherited, not derived per window.** Its bullets synthesize
across multiple claims and are not tied to individual events, so R1 does not
apply to them in the same way, and they carry no evidence links. Section 1 is
not scored.
