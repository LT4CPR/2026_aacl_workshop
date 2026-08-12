#!/usr/bin/env python3
"""Measure whether each report statement is supported by the tweets cited for it.

Rule R1 keeps a bullet when at least one tweet expresses one of its events. That
guarantees the event is present; it does not guarantee the tweets state what the
bullet says. A bullet can survive on evidence that names the event and drops its
specifics: "the alert level moved from Green to Yellow" evidenced by tweets that
say only "tremor reported".

Lexical overlap is not a usable measure here. It scores a correct paraphrase
("No fatalities were reported" against "No fatalities - Ardley") as unsupported,
and a shared topic word as supported. This uses natural language inference
instead: each bullet is the hypothesis, its cited tweets are the premise, and the
model judges entailment.

Bullets are decomposed into atomic claims before scoring. A report statement
routinely carries two or three claims -- "Emergency chlorination was started and
chlorine residual returned to target range" -- and entailment requires the whole
hypothesis, so scoring the compound sentence reports neutral even when the
evidence states one conjunct almost verbatim. Without decomposition the measure
is dominated by that effect and understates support severely.

Each claim is scored, and each bullet is characterised by the fraction of its
claims that are supported:

  supported          every claim entailed
  partly_supported   some but not all claims entailed
  contradicted       a claim is contradicted by the evidence
  unsupported        no claim entailed and none contradicted
  no_evidence        the bullet cites no tweets

Contradiction judgments on this domain should be read with caution: the premise
is a concatenation of informal posts, which is far from the clean sentence pairs
these models are trained on, and spot checks found confident contradictions that
are not contradictions.

Usage:
  python3 audit_faithfulness.py --export-dir EXPORT [--split train]
      [--sections 3,4,5,6,7,8,9,10,11] [--model MODEL] [--limit N]
      [--out-json report.json]

Requires transformers and torch. The default model is a public MNLI checkpoint;
any sequence-classification model with entailment/neutral/contradiction labels
works.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

__version__ = "1.1"

DEFAULT_MODEL = "microsoft/deberta-large-mnli"

# Finite verbs, used to decide whether a coordinated segment is its own clause
# rather than a conjoined noun phrase.
_VERB = re.compile(
    r"\b(was|were|is|are|has|have|had|will|would|began|started|reached|rose|fell|"
    r"opened|closed|issued|ordered|reported|confirmed|declared|returned|resumed|"
    r"remained|continued|received|provided|treated|evacuated|deployed|held|met|"
    r"agreed|announced|lifted|extended|reduced|raised|lowered|suspended|"
    r"distributed|recorded|identified|\w+ed|\w+s)\b", re.I)
# Trailing modifiers that carry a claim of their own.
_MODIFIER = re.compile(
    r",\s+(?=(?:with|attended|including|leaving|bringing|affecting|causing|"
    r"prompting)\b)")


def decompose(text: str):
    """Split a report statement into atomic claims."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    out = []
    for part in (p for p in re.split(r";\s+", t) if p.strip()):
        segs = re.split(r",?\s+(?:and|but|while|whereas)\s+", part)
        merged = []
        for seg in segs:
            # a segment with no verb is a conjoined phrase, not a clause
            if merged and not _VERB.search(seg):
                merged[-1] = merged[-1] + " and " + seg
            else:
                merged.append(seg)
        for seg in merged:
            out.extend(_MODIFIER.split(seg))
    claims = [re.sub(r"^(and|but|with)\s+", "", c).strip(" .,") for c in out]
    claims = [c for c in claims if len(c.split()) >= 3]
    return claims or [t]
# Premise length is capped so a long evidence set does not push the hypothesis
# out of the model's window.
MAX_PREMISE_CHARS = 1500


def load_cells(export_dir: Path, split: str):
    """Yield (cell name, report, {tweet id: text})."""
    root = export_dir / split
    if not root.exists():
        root = export_dir
    for report_path in sorted(root.rglob("*.report.json")):
        tweets_path = report_path.with_name(
            report_path.name.replace(".report.json", ".tweets.jsonl"))
        if not tweets_path.exists():
            continue
        tweets = {}
        for line in tweets_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("record_type") == "tweet":
                tweets[r["id"]] = r["text"]
        yield (report_path.name.replace(".report.json", ""),
               json.loads(report_path.read_text(encoding="utf-8")),
               tweets)


def build_pairs(export_dir: Path, split: str, sections: set):
    pairs = []
    for cell, report, tweets in load_cells(export_dir, split):
        doc = cell.split(".")[0]
        for sec in report.get("sections", []):
            if sections and sec.get("id") not in sections:
                continue
            for sub in sec.get("subsections", []):
                for b in sub.get("bullets", []):
                    ids = b.get("tweet_ids") or []
                    premise = " ".join(tweets.get(i, "") for i in ids)[:MAX_PREMISE_CHARS]
                    pairs.append({
                        "cell": cell, "doc": doc, "section": sec.get("id"),
                        "bullet_id": b.get("id"), "hypothesis": b.get("text", ""),
                        "claims": decompose(b.get("text", "")),
                        "n_evidence": len(ids), "premise": premise,
                    })
    return pairs


def classify(pairs, model_name, batch_size=16):
    """Label each pair entailment / neutral / contradiction."""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name)
    model.eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    print(f"[cfg] model={model_name} device={device}")

    # Label order differs between checkpoints; read it rather than assume.
    id2label = {i: l.lower() for i, l in model.config.id2label.items()}

    # One item per claim, so a compound statement is not judged as a whole.
    items = [(p, c) for p in pairs if p["n_evidence"] > 0 for c in p["claims"]]
    print(f"[cfg] {len(pairs)} bullets -> {len(items)} claims "
          f"({len(items)/max(len(pairs),1):.2f} per bullet)")

    for start in range(0, len(items), batch_size):
        batch = items[start:start + batch_size]
        enc = tok([p["premise"] for p, _ in batch], [c for _, c in batch],
                  return_tensors="pt", truncation=True, padding=True, max_length=512)
        enc = {k: v.to(device) for k, v in enc.items()}
        with torch.no_grad():
            probs = model(**enc).logits.softmax(-1).cpu()
        for (p, claim), row in zip(batch, probs):
            scores = {id2label[i]: float(row[i]) for i in range(len(row))}
            p.setdefault("claim_results", []).append({
                "claim": claim,
                "nli": max(scores, key=scores.get),
                "scores": {k: round(v, 4) for k, v in scores.items()},
            })
        if (start + batch_size) % 320 == 0 or start + batch_size >= len(items):
            print(f"[..] {min(start + batch_size, len(items))}/{len(items)}", flush=True)
    return pairs


def state(pair):
    if pair["n_evidence"] == 0:
        return "no_evidence"
    results = pair.get("claim_results") or []
    if not results:
        return "unsupported"
    labels = [r["nli"] for r in results]
    n_ent = sum(1 for l in labels if "entail" in l)
    pair["claim_coverage"] = round(n_ent / len(labels), 3)
    if any("contradict" in l for l in labels):
        return "contradicted"
    if n_ent == len(labels):
        return "supported"
    if n_ent:
        return "partly_supported"
    return "unsupported"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export-dir", type=Path, required=True)
    ap.add_argument("--split", default="train")
    ap.add_argument("--sections", default="3,4,5,6,7,8,9,10,11")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--limit", type=int, default=0, help="sample N pairs (0 = all)")
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--out-json", type=Path, default=None)
    a = ap.parse_args()
    print(f"[cfg] audit_faithfulness.py v{__version__} split={a.split}")

    sections = {s.strip() for s in a.sections.split(",") if s.strip()}
    pairs = build_pairs(a.export_dir, a.split, sections)
    if not pairs:
        print(f"no report/tweet pairs found under {a.export_dir}/{a.split}")
        return 1
    if a.limit and a.limit < len(pairs):
        import random
        pairs = random.Random(7).sample(pairs, a.limit)
    print(f"[OK] {len(pairs)} bullets in sections {sorted(sections)}")

    pairs = classify(pairs, a.model, a.batch_size)
    for p in pairs:
        p["state"] = state(p)

    counts = Counter(p["state"] for p in pairs)
    total = len(pairs)
    print(f"\n{'state':18s} {'count':>7s} {'share':>7s}")
    for s in ("supported", "partly_supported", "unsupported", "contradicted",
              "no_evidence"):
        print(f"{s:18s} {counts[s]:7d} {100*counts[s]/max(total,1):6.1f}%")

    cov = [p["claim_coverage"] for p in pairs if "claim_coverage" in p]
    if cov:
        print(f"\nclaim coverage: mean {statistics.mean(cov):.2f} "
              f"median {statistics.median(cov):.2f} "
              f"| bullets with every claim supported "
              f"{100*sum(1 for c in cov if c == 1)/len(cov):.0f}%"
              f" | with none {100*sum(1 for c in cov if c == 0)/len(cov):.0f}%")

    by_doc = defaultdict(Counter)
    by_sec = defaultdict(Counter)
    for p in pairs:
        by_doc[p["doc"]][p["state"]] += 1
        by_sec[p["section"]][p["state"]] += 1

    def any_support(c):
        n = sum(c.values())
        return 100 * (c["supported"] + c["partly_supported"]) / max(n, 1)

    print(f"\n{'document':12s} {'n':>5s} {'full':>7s} {'any':>7s}")
    for doc in sorted(by_doc):
        c = by_doc[doc]; n = sum(c.values())
        print(f"{doc:12s} {n:5d} {100*c['supported']/max(n,1):6.0f}% {any_support(c):6.0f}%")

    print(f"\n{'section':8s} {'n':>5s} {'full':>7s} {'any':>7s}")
    for sec in sorted(by_sec, key=lambda x: int(x) if x.isdigit() else 99):
        c = by_sec[sec]; n = sum(c.values())
        print(f"{sec:8s} {n:5d} {100*c['supported']/max(n,1):6.0f}% {any_support(c):6.0f}%")

    # A contradiction is a defect rather than a gap, so surface these directly.
    contra = [p for p in pairs if p["state"] == "contradicted"]
    if contra:
        print(f"\ncontradicted ({len(contra)}), first few:")
        for p in contra[:5]:
            print(f"  [{p['cell']} {p['bullet_id']}] {p['hypothesis'][:80]}")

    unsup = [p for p in pairs if p["state"] == "unsupported"]
    if unsup:
        print(f"\nunsupported ({len(unsup)}), first few:")
        for p in unsup[:5]:
            print(f"  [{p['cell']} {p['bullet_id']}] {p['hypothesis'][:80]}")

    if a.out_json:
        a.out_json.write_text(json.dumps({
            "version": __version__, "model": a.model, "split": a.split,
            "sections": sorted(sections), "total": total,
            "counts": dict(counts),
            "per_document": {k: dict(v) for k, v in by_doc.items()},
            "per_section": {k: dict(v) for k, v in by_sec.items()},
            "pairs": pairs,
        }, indent=1), encoding="utf-8")
        print(f"\n[OK] wrote {a.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
