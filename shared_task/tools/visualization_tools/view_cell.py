#!/usr/bin/env python3
"""Render one training pair as a single self-contained HTML page.

Shows the tweets and the reference report side by side, linked by evidence:
selecting a statement illuminates the tweets that support it, and selecting a
tweet illuminates the statements it supports. That relationship is the task,
and it is the thing a static listing cannot show.

Usage:
  python3 view_cell.py CELL_STEM [-o OUT.html] [--open]
  python3 view_cell.py data/train/volcano/volcano.W2.k1

CELL_STEM is the path without the .tweets.jsonl / .report.json suffix. The
report is optional: test cells render with the stream alone.

Output is one HTML file with no external dependencies, so it works offline.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import webbrowser
from pathlib import Path

CONF_ORDER = {"confirmed": 0, "announced": 1, "potential": 2, "absent": 3}


def load(stem: Path):
    tweets_path = Path(f"{stem}.tweets.jsonl")
    if not tweets_path.exists():
        raise SystemExit(f"not found: {tweets_path}")
    crisis, window, tweets = {}, {}, []
    for line in tweets_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        kind = r.get("record_type")
        if kind == "crisis":
            crisis = r
        elif kind == "window":
            window = r
        elif kind == "tweet":
            tweets.append(r)
    report_path = Path(f"{stem}.report.json")
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
    return crisis, window, tweets, report


def linkify(text: str) -> str:
    """Mark up hashtags, mentions and links so the stream reads like a stream.

    quote=False matters: escaping an apostrophe yields the numeric reference
    &#x27;, and the hashtag pattern then matches "#x27" inside it, splitting
    the reference apart so it renders literally ("can&#x27;t look"). Quotes and
    apostrophes need no escaping in a text node. The lookbehind is a second
    guard, for any &#nnn; already present in the source.
    """
    out = html.escape(text, quote=False)
    out = re.sub(r"(https?://\S+)", r'<span class="u">\1</span>', out)
    out = re.sub(r"(?<!&)(#\w+)", r'<span class="h">\1</span>', out)
    out = re.sub(r"(@\w+)", r'<span class="m">\1</span>', out)
    out = re.sub(r"^(RT(?:\s@\w+)?:)", r'<span class="rt">\1</span>', out)
    return out


def short_time(ts: str) -> str:
    m = re.match(r"\w{3} (\w{3}) (\d{2}) (\d{2}:\d{2})", ts or "")
    if m:
        return f"{m.group(2)} {m.group(1)} {m.group(3)}"
    return (ts or "")[:16]


CSS = """
:root{
  --paper:#e9ebee; --card:#fff; --ink:#15181c; --muted:#6a727c;
  --rule:#ccd2d8; --link:#0f5f52; --link-soft:#d8ece7;
  --warn:#8a5a12; --warn-soft:#f3e6d0;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);
     font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
header{border-bottom:1px solid var(--rule);background:var(--card);
       padding:22px 28px 18px}
h1{margin:0 0 4px;font-size:19px;font-weight:620;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:13px}
.bar{margin-top:14px;font-family:var(--mono);font-size:11.5px;
     color:var(--muted);display:flex;gap:22px;flex-wrap:wrap;
     border-top:1px solid var(--rule);padding-top:11px}
.bar b{color:var(--ink);font-weight:600}
main{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);
     gap:1px;background:var(--rule);min-height:calc(100vh - 130px)}
section{background:var(--paper);padding:20px 24px 60px;overflow-y:auto;
        max-height:calc(100vh - 130px)}
.colhead{font-family:var(--mono);font-size:11px;letter-spacing:.09em;
         text-transform:uppercase;color:var(--muted);margin:0 0 14px;
         display:flex;justify-content:space-between;align-items:baseline}
.hint{font-family:var(--sans);text-transform:none;letter-spacing:0;font-size:12px}

/* stream */
.tw{background:var(--card);border:1px solid var(--rule);border-radius:3px;
    padding:9px 12px;margin-bottom:7px;cursor:pointer;transition:.12s}
.tw:hover{border-color:#9aa3ac}
.tw .meta{font-family:var(--mono);font-size:11px;color:var(--muted);
          display:flex;gap:10px;margin-bottom:3px}
.tw .id{color:var(--ink);font-weight:600;min-width:2.4em}
.tw .src{letter-spacing:.02em}
.tw .txt{font-size:14px;word-wrap:break-word}
.h{color:var(--link)} .m{color:#5b4a8a} .u{color:var(--muted)}
.rt{font-family:var(--mono);font-size:12px;color:var(--muted)}
.tw.lit{border-color:var(--link);box-shadow:inset 3px 0 0 var(--link);
        background:var(--link-soft)}
.tw.dim{opacity:.32}

/* report */
.sec{margin-bottom:18px}
.sec > h2{font-size:12px;font-family:var(--mono);letter-spacing:.06em;
          text-transform:uppercase;color:var(--muted);margin:0 0 8px;
          padding-bottom:5px;border-bottom:1px solid var(--rule)}
.sec > h2 span{color:var(--ink)}
.sub-h{font-size:12.5px;font-weight:640;margin:11px 0 5px;color:#3a424c}
.b{background:var(--card);border:1px solid var(--rule);border-radius:3px;
   padding:8px 11px;margin-bottom:5px;cursor:pointer;transition:.12s;
   display:flex;gap:10px;align-items:flex-start}
.b:hover{border-color:#9aa3ac}
.b.lit{border-color:var(--link);box-shadow:inset 3px 0 0 var(--link);
       background:var(--link-soft)}
.b.dim{opacity:.32}
.b .bid{font-family:var(--mono);font-size:10.5px;color:var(--muted);
        min-width:3.1em;padding-top:2px}
.b .btxt{font-size:14px}
.cf{font-family:var(--mono);font-size:9.5px;letter-spacing:.07em;
    text-transform:uppercase;padding:1px 0;margin-left:auto;white-space:nowrap;
    color:var(--muted);padding-top:3px}
.cf.potential,.cf.announced{color:var(--warn)}
.ev{font-family:var(--mono);font-size:10.5px;color:var(--link);margin-top:3px}
.none{color:var(--muted);font-size:13px;padding:18px 0}
@media (max-width:860px){
  main{grid-template-columns:1fr}
  section{max-height:none}
}
"""

JS = """
const EV = __EV__;      // bullet id -> [tweet ids]
const REV = {};         // tweet id -> [bullet ids]
for (const [b, ids] of Object.entries(EV))
  for (const t of ids) (REV[t] = REV[t] || []).push(b);

let active = null;
const all = sel => [...document.querySelectorAll(sel)];

function clear(){
  all('.tw,.b').forEach(e => e.classList.remove('lit','dim'));
  active = null;
}
function light(tweetIds, bulletIds){
  const T = new Set(tweetIds.map(String)), B = new Set(bulletIds);
  all('.tw').forEach(e => {
    const on = T.has(e.dataset.id);
    e.classList.toggle('lit', on); e.classList.toggle('dim', !on);
  });
  all('.b').forEach(e => {
    const on = B.has(e.dataset.id);
    e.classList.toggle('lit', on); e.classList.toggle('dim', !on);
  });
  const first = document.querySelector('.tw.lit');
  if (first) first.scrollIntoView({block:'nearest', behavior:'smooth'});
}
function select(key, isBullet){
  if (active === key) { clear(); return; }
  active = key;
  if (isBullet) light(EV[key] || [], [key]);
  else light([key], REV[key] || []);
}
document.addEventListener('click', e => {
  const b = e.target.closest('.b'), t = e.target.closest('.tw');
  if (b) select(b.dataset.id, true);
  else if (t) select(t.dataset.id, false);
  else if (!e.target.closest('header')) clear();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') clear(); });
"""


def render(crisis, window, tweets, report, stem_name) -> str:
    ev_map = {}
    body = []

    if report:
        for sec in report.get("sections", []):
            subs = []
            for sub in sec.get("subsections", []):
                bl = []
                for b in sub.get("bullets", []):
                    bid = b.get("id", "")
                    ids = [str(i) for i in (b.get("tweet_ids") or [])]
                    if ids:
                        ev_map[bid] = ids
                    conf = b.get("confidence", "")
                    ev = (f'<div class="ev">{len(ids)} source'
                          f'{"s" if len(ids) != 1 else ""}: {", ".join(ids[:8])}'
                          f'{"…" if len(ids) > 8 else ""}</div>') if ids else ""
                    bl.append(
                        f'<div class="b" data-id="{html.escape(bid)}">'
                        f'<div class="bid">{html.escape(bid)}</div>'
                        f'<div><div class="btxt">{html.escape(b.get("text",""))}</div>{ev}</div>'
                        f'<div class="cf {html.escape(conf)}">{html.escape(conf)}</div></div>')
                if bl:
                    subs.append(f'<div class="sub-h">{html.escape(sub.get("title",""))}</div>'
                                + "".join(bl))
            if subs:
                body.append(f'<div class="sec"><h2>{html.escape(sec.get("id",""))} '
                            f'<span>{html.escape(sec.get("title",""))}</span></h2>'
                            + "".join(subs) + "</div>")
        report_html = "".join(body) or '<div class="none">No sections.</div>'
        n_bullets = sum(len(s.get("bullets", [])) for sec in report.get("sections", [])
                        for s in sec.get("subsections", []))
        rhead = f'<div class="colhead">Reference report <span class="hint">{n_bullets} statements</span></div>'
    else:
        report_html = ('<div class="none">No reference report for this cell. '
                       'Test inputs are released without reports.</div>')
        rhead = '<div class="colhead">Reference report</div>'

    stream = "".join(
        f'<div class="tw" data-id="{t.get("id")}">'
        f'<div class="meta"><span class="id">{t.get("id")}</span>'
        f'<span class="src">{html.escape(t.get("information_source",""))}</span>'
        f'<span>{html.escape(short_time(t.get("timestamp","")))}</span></div>'
        f'<div class="txt">{linkify(t.get("text",""))}</div></div>'
        for t in tweets)

    bits = [x for x in (crisis.get("hazard"), crisis.get("location")) if x]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(window.get('cell_id', stem_name))}</title>
<style>{CSS}</style></head><body>
<header>
  <h1>{html.escape(crisis.get('title', stem_name))}</h1>
  <div class="sub">{html.escape('  ·  '.join(bits))}</div>
  <div class="bar">
    <span><b>{html.escape(window.get('cell_id', stem_name))}</b></span>
    <span>reporting window <b>{html.escape(str(window.get('start','')))}</b>
      to <b>{html.escape(str(window.get('end','')))}</b></span>
    <span><b>{len(tweets)}</b> tweets</span>
    <span>event span {html.escape(str(crisis.get('period','')))}</span>
  </div>
</header>
<main>
  <section>
    <div class="colhead">Tweets<span class="hint">select to see what it supports</span></div>
    {stream}
  </section>
  <section>
    {rhead}
    {report_html}
  </section>
</main>
<script>{JS.replace('__EV__', json.dumps(ev_map))}</script>
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stem", help="cell path without .tweets.jsonl / .report.json")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--open", action="store_true", help="open in a browser")
    a = ap.parse_args()

    stem = Path(a.stem)
    crisis, window, tweets, report = load(stem)
    out = Path(a.output) if a.output else stem.with_suffix(".html")
    out.write_text(render(crisis, window, tweets, report, stem.name), encoding="utf-8")
    print(f"{out}  ({len(tweets)} tweets"
          + (f", {sum(len(s.get('bullets', [])) for sec in report.get('sections', []) for s in sec.get('subsections', []))} statements)"
             if report else ", no report)"))
    if a.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
