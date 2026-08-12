# Datasheet

**Synthetic Crisis Situation Report Corpus**

Prepared for the LT4CPR Shared Task on Automatic Situation Report Generation,
First Workshop on Language Technologies for Crisis Preparedness and Response
(LT4CPR), AACL-IJCNLP 2026, Hengqin, Zhuhai, China, November 9, 2026.

| | |
| --- | --- |
| Version | 1.0 (training data) |
| Released | August 7, 2026 |
| Task page | https://lt4cpr.github.io/aacl2026-workshop-LT4CPR/shared-task.html |
| Contact | lt4cpr.sharedtask@gmail.com |
| License | MIT |

---

## 1. Motivation

The corpus supports the LT4CPR Shared Task on Automatic Situation Report
Generation. During a crisis, responders must rapidly synthesize large volumes
of fragmented, repetitive, uncertain and sometimes conflicting information.
Social media carries timely reports about hazards, impacts, infrastructure
damage, affected populations, urgent needs and response activities, but turning
those messages into an operationally useful overview remains labor-intensive.
The shared task asks whether language technologies can produce concise,
structured and verifiable situation reports from such streams.

Real annotated data for this task is scarce. Producing a reference situation
report for a real event requires expert annotation over thousands of posts, and
platform terms frequently prevent redistributing the posts themselves. The two
constraints compound: the datasets that exist are small, and those that are
large cannot be shared.

The corpus addresses this by generating crises rather than collecting them.
Because every post is generated from a record of what it reports, the
relationship between a set of posts and its reference report is exact rather
than a matter of annotator judgment, and the data can be released without
restriction.

---

## 2. Composition

| | |
| --- | --- |
| Crisis documents | 10: 8 training, 2 development |
| Training pairs (cells) | 140 training, 23 development |
| Tweets | 9,848 |
| Tweets per document | 972 to 997 |
| Bullets per reference report | 8 to 93, median 31 |

Each document is one fictional crisis with its own places, organizations,
hazard and timeline. Each is divided into four cumulative time windows, and
each window is sampled repeatedly, producing pairs that differ in how much
evidence they contain.

Documents cover an earthquake, an armed conflict, a wildfire, a power failure,
a flood, a disease outbreak, a chemical release, a ferry sinking, a volcanic
eruption, and a crowd crush. Each was built around a specific difficulty:
reporting a crisis with no fatalities, tracking figures revised in both
directions, distinguishing casualty categories that must not be summed,
recognizing superseded guidance, following a staged official status, handling
corrections and rumors, working from eyewitness accounts alone, and reporting
during a forecast phase before the main event.

Roughly 15 percent of posts in each document are off topic: ordinary social
media content unrelated to the crisis, present because real crisis streams
contain it.

---

## 3. Collection and generation

No data was collected from any platform. The corpus is generated.

For each crisis, a complete reference report is authored first. A canonical
graph is derived from it, recording each event, its participants, and which
report statements it supports. Posts are then generated from that graph, so
every post carries a record of exactly what it reports. Reference reports for
individual samples are derived mechanically from the complete report by fixed
rules, documented in `DERIVATION_RULES.md`.

All content is fictional. Names of places, organizations and people do not
refer to real entities, and any resemblance is unintended.

**Calibration against real corpora.** Structural and temporal properties were
measured from annotated corpora of real events (LAX 2013, Colorado 2012, Savar
2013, Costa Rica 2012, Philippines 2012) and used to set generation
parameters: the timing of posts by source category, the mix of sources, rates
of hashtags, mentions, retweets and URLs, orthographic conventions, and the
proportion of off-topic content.

No content from those corpora appears in this corpus, and none of them is
redistributed here. They remain under their own licenses. Only aggregate
statistics informed the parameters.

Generation is deterministic: the same inputs and seed reproduce the corpus
byte for byte.

---

## 4. Preprocessing and labeling

Labels are produced by construction rather than annotation. Each post is
generated from a plan recording which events it expresses; each report
statement records which posts support it. There are no annotation guidelines
and no inter-annotator agreement figures, because there was no annotation
process.

Reference reports for individual samples are derived from the complete report
by released rules. Statement text is taken verbatim from the complete report;
the rules select, drop and relabel, and do not rewrite.

Post text passes through a template composer and, for most posts, a
constrained language-model rewrite that varies phrasing while preserving the
content the plan specifies. Rewrites that alter the specified content are
rejected and the template text is used instead.

---

## 5. Uses

The corpus is intended for training and evaluating systems that produce
structured situation reports from crisis social media.

**Suitable for:** structured summarization, evidence-grounded generation,
confidence calibration under partial information, and studying how reports
should change as evidence accumulates.

**Not suitable for:** studying real crisis communication, the linguistic
behavior of real social media users, or the epidemiology, casualty patterns or
response effectiveness of real events. The content is invented, and its
statistical realism extends only to the properties listed in section 3.

Systems trained on this corpus have not been shown to transfer to real crisis
data. Transfer is an open question the shared task is intended to help answer.

---

## 6. Limitations

Stated because they affect what the data can support.

**Reference statements can assert more than their cited posts state.** This is
the most consequential limitation and takes two forms.

The first is partial attestation: a statement supported by several posts
survives when at least one of them is present, so it can be retained on a
subset of its evidence. This concentrates in the earliest windows.

The second is more general. Rule R1 keeps a statement when a post expresses one
of its events; it does not require the post to state what the statement says.
Because surface realization preserves the event and its principal entity but
not every attribute, a statement can survive on evidence that names the event
and omits its specifics. A statement recording that an alert level moved from
Green to Yellow, for example, may cite posts that report only a tremor. Numeric
figures were made first-class content during development and are now stated in
the posts that evidence them, but named categorical values -- alert levels,
order states, thresholds -- were not given the same treatment.

An entailment-based audit of the released reference statements is provided with
the release (`audit_faithfulness.py`), classifying each statement against its
cited posts as supported, unsupported, or contradicted. Users evaluating
faithfulness should be aware that the reference itself is not fully entailed by
the posts, and should consult that audit before treating reference statements as
a faithfulness ceiling.

**Confidence labels are unevenly distributed.** Roughly three quarters of
statements are `confirmed` and one quarter `unconfirmed`. The released
vocabulary is binary; a finer four-level scheme is retained internally but
three of its levels were too sparse to learn or score reliably.

**Figure extraction is heuristic.** The derivation rules locate numeric figures
by pattern matching, so unusual phrasings can be missed and a small number of
figure-bearing statements may be retained or dropped incorrectly.

**Post text is generated, not written.** Composed from templates and varied by
a constrained rewrite, it is more uniform than real social media. Known
residual artifacts in this version: a small number of posts (fewer than ten
across the corpus) contain awkward phrasing from the composer.

**About one post in forty-five is an exact duplicate**, close to the one in
forty measured in the real corpora used for calibration.

**Sampling parameters are set against a proxy statistic.** The dropout rate and
the number of samples per window were chosen to produce a target rate of change
in the reference reports, not against measured system performance, which did
not exist when they were set.

---

## 7. Release schedule

This datasheet accompanies the training release. Later components follow the
shared task schedule.

| Component | Date |
| --- | --- |
| Training and development data | August 7, 2026 |
| Evaluation metrics, baselines and validation scripts | August 7 to September 1, 2026 |
| Test data | September 1, 2026 |
| System output submission deadline | September 7, 2026 |

Two of the ten documents are held out as a development set, released alongside
the training documents but kept separate so that tuning does not happen on the
data a system was fitted to. Test documents are new crises, distinct from all
ten released here. Test inputs will be released without reference reports; the
reports will be published after the submission deadline.

---

## 8. Distribution and license

Distributed under the MIT License. Copyright 2026, the organizers of the LT4CPR
workshop and shared task. See `LICENSE`.

This covers the synthetic corpus, the taxonomy, the generation pipeline and the
documentation. The real corpora used for calibration are not included and are
separately licensed.

---

## 9. Ethics and responsible use

The corpus contains no real personal information: all content is generated, and
the people, organizations and places in it do not exist. It therefore carries
none of the privacy risks attached to real crisis social media.

Two cautions apply nonetheless.

Systems developed on this corpus produce research artifacts. They must not be
treated as verified operational intelligence, nor used as a substitute for
expert review and established emergency-management procedures. Automated
reports in high-stakes environments carry risks of hallucination and of
confident error that this corpus is designed to measure, not to eliminate.

Reports generated from synthetic crises may not behave the same way on real
streams, which carry distressing content, rumors and references to vulnerable
populations. Transfer to real data is unshown; see section 5.

---

## 10. Maintenance

Maintained by the shared task organizers, lt4cpr.sharedtask@gmail.com.
Corrections and regenerated versions are published with a version identifier.
The generation pipeline is released alongside the data, so any released version
can be reproduced from its inputs and seed.

---

## 11. Funding

This material is based upon work supported by the National Science Foundation
under Grant Nos. 2346334 and 2346335. Any opinions, findings, and conclusions
or recommendations expressed in this material are those of the authors and do
not necessarily reflect the views of the National Science Foundation.

---

## 12. Citation

A shared task overview paper will be published in the LT4CPR proceedings.
Until it is available, cite the task page:

> LT4CPR Shared Task on Automatic Situation Report Generation. First Workshop
> on Language Technologies for Crisis Preparedness and Response, AACL-IJCNLP
> 2026. https://lt4cpr.github.io/aacl2026-workshop-LT4CPR/shared-task.html
