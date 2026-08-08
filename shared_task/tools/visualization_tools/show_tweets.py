#!/usr/bin/env python3
"""Display generated tweets in a readable form.

Reads either format:
  * released participant files  ({cell}.tweets.jsonl, with crisis/window headers)
  * internal corpus files       (l4/{doc}.synthetic_tweets_*.jsonl)

Usage:
  python3 show_tweets.py FILE [options]

  -n, --limit N        show at most N tweets (default 40; 0 for all)
  -s, --source SRC     filter by source/voice, repeatable
                       (official, media, eyewitness, citizen, humanitarian, ...)
  -g, --grep PATTERN   show only tweets whose text matches this regex
  --noise              include off-topic tweets (hidden by default in
                       internal files, where plan_type marks them)
  --only-noise         show only off-topic tweets
  --plain              no colour, no wrapping - for piping or logs
  --stats              print a summary instead of the tweets
  -w, --width N        wrap width (default: terminal width, capped at 100)

Examples:
  python3 show_tweets.py work/participant_export/released/volcano/volcano.W1.k1.tweets.jsonl
  python3 show_tweets.py work/l4/volcano.synthetic_tweets_surfaced.jsonl --stats
  python3 show_tweets.py work/l4/ferry.synthetic_tweets_surfaced.jsonl -s official -g "rescued|missing"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from collections import Counter
from datetime import datetime

# Source-category colours. Kept muted so the text stays the focus.
C = {
    "reset": "\033[0m", "dim": "\033[2m", "bold": "\033[1m",
    "official": "\033[34m", "government": "\033[34m",
    "media": "\033[35m",
    "eyewitness": "\033[31m",
    "humanitarian": "\033[36m", "ngos": "\033[36m",
    "citizen": "\033[32m", "outsiders": "\033[32m",
    "party_to_conflict": "\033[33m",
    "noise": "\033[90m", "not labeled": "\033[90m",
}
HASHTAG = re.compile(r"(#\w+)")
MENTION = re.compile(r"(@\w+)")
URL = re.compile(r"(https?://\S+)")


def supports_colour(plain: bool) -> bool:
    if plain or os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def load(path: str):
    """Return (header, records). Header is None for internal corpus files."""
    header, records = {}, []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            rt = obj.get("record_type")
            if rt in ("crisis", "window"):
                header[rt] = obj
            else:
                records.append(obj)
    return (header or None), records


def normalise(rec: dict) -> dict:
    """Map either file format onto one shape."""
    if "record_type" in rec or "information_source" in rec:
        src = rec.get("information_source", "")
        return {
            "id": rec.get("id"),
            "text": rec.get("text", ""),
            "source": src,
            "timestamp": rec.get("timestamp", ""),
            "is_noise": src == "Not labeled",
        }
    voice = (rec.get("style_profile") or {}).get("voice", "")
    return {
        "id": rec.get("tweet_id"),
        "text": rec.get("tweet_text", ""),
        "source": voice,
        "timestamp": rec.get("timestamp", ""),
        "is_noise": rec.get("plan_type") == "noise_tweet",
    }


def fmt_time(ts: str) -> str:
    if not ts:
        return ""
    for f in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(ts.replace("Z", "+0000"), f).strftime("%b %d %H:%M")
        except ValueError:
            continue
    return ts[:16]


def wrap(text: str, width: int, indent: str) -> list:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return [lines[0]] + [indent + l for l in lines[1:]] if lines else [""]


def highlight(text: str, colour: bool) -> str:
    if not colour:
        return text
    text = HASHTAG.sub(f"\033[36m\\1{C['reset']}", text)
    text = MENTION.sub(f"\033[35m\\1{C['reset']}", text)
    text = URL.sub(f"{C['dim']}\\1{C['reset']}", text)
    return text


def print_header(header: dict, colour: bool) -> None:
    if not header:
        return
    b = C["bold"] if colour else ""
    d = C["dim"] if colour else ""
    r = C["reset"] if colour else ""
    c, w = header.get("crisis", {}), header.get("window", {})
    if c:
        print(f"{b}{c.get('title', '')}{r}")
        bits = [x for x in (c.get("hazard"), c.get("location"), c.get("period")) if x]
        if bits:
            print(f"{d}{'  |  '.join(bits)}{r}")
    if w:
        print(f"{d}{w.get('cell_id', '')}   {fmt_time(w.get('start', ''))} "
              f"-> {fmt_time(w.get('end', ''))}   {w.get('n_tweets', '')} tweets{r}")
    print()


def print_stats(records: list) -> None:
    src = Counter(r["source"] or "(none)" for r in records)
    noise = sum(1 for r in records if r["is_noise"])
    texts = [r["text"] for r in records]
    lens = [len(t) for t in texts]
    print(f"tweets            {len(records)}")
    print(f"off-topic         {noise} ({100 * noise / max(len(records), 1):.0f}%)")
    print(f"distinct texts    {len(set(texts))}")
    print(f"median length     {sorted(lens)[len(lens) // 2] if lens else 0} chars")
    for name, pat in (("with hashtag", r"#\w+"), ("with mention", r"@\w+"),
                      ("with URL", r"https?://"), ("retweets", r"^RT "),
                      ("with a digit", r"\d")):
        n = sum(1 for t in texts if re.search(pat, t))
        print(f"{name:17s} {n:4d} ({100 * n / max(len(texts), 1):3.0f}%)")
    print("\nby source:")
    for k, v in src.most_common():
        print(f"  {k:20s} {v:4d} ({100 * v / max(len(records), 1):3.0f}%)")
    tags = Counter(t for text in texts for t in re.findall(r"#\w+", text))
    if tags:
        print("\ntop hashtags:")
        for k, v in tags.most_common(8):
            print(f"  {k:24s} {v}")


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("file")
    ap.add_argument("-n", "--limit", type=int, default=40)
    ap.add_argument("-s", "--source", action="append", default=[])
    ap.add_argument("-g", "--grep", default=None)
    ap.add_argument("--noise", action="store_true")
    ap.add_argument("--only-noise", action="store_true")
    ap.add_argument("--plain", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("-w", "--width", type=int, default=None)
    a = ap.parse_args()

    header, raw = load(a.file)
    records = [normalise(r) for r in raw]
    if not records:
        print(f"no tweet records found in {a.file}", file=sys.stderr)
        return 1

    colour = supports_colour(a.plain)
    width = a.width or min(shutil.get_terminal_size((100, 24)).columns, 100)

    if a.stats:
        print_header(header, colour)
        print_stats(records)
        return 0

    shown = records
    if a.only_noise:
        shown = [r for r in shown if r["is_noise"]]
    elif not a.noise and header is None:
        # internal files mark noise explicitly; released files do not, so the
        # default only filters where the distinction is reliable
        shown = [r for r in shown if not r["is_noise"]]
    if a.source:
        want = {s.lower() for s in a.source}
        shown = [r for r in shown if r["source"].lower() in want]
    if a.grep:
        pat = re.compile(a.grep, re.I)
        shown = [r for r in shown if pat.search(r["text"])]

    total = len(shown)
    if a.limit > 0:
        shown = shown[:a.limit]

    print_header(header, colour)
    idw = max((len(str(r["id"])) for r in shown), default=3)
    for r in shown:
        key = r["source"].lower()
        col = C.get(key, "") if colour else ""
        rst = C["reset"] if colour else ""
        dim = C["dim"] if colour else ""
        gutter = f"{str(r['id']):>{idw}}  "
        meta = f"{col}{r['source'] or '-':<12}{rst} {dim}{fmt_time(r['timestamp'])}{rst}"
        body = highlight(r["text"], colour)
        lines = wrap(r["text"], width - idw - 2, " " * (idw + 2))
        if colour:
            lines = [highlight(l, True) for l in lines]
        print(f"{dim}{gutter}{rst}{meta}")
        for l in lines:
            print(f"{' ' * (idw + 2)}{l}")
        print()

    if total > len(shown):
        print(f"... {total - len(shown)} more (use -n 0 to show all)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
