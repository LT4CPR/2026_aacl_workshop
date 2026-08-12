#!/usr/bin/env python3
"""
sitrep2html.py - render a situation report JSON as a standalone HTML page.

Usage:
    python3 sitrep2html.py INPUT.json [OUTPUT.html]

If OUTPUT.html is omitted, it is written next to the input with the same
basename (e.g. earthquake-gold.json -> earthquake-gold.html).

The JSON is embedded in the page, so the output is a single self-contained
file with no runtime dependencies beyond Google Fonts (degrades gracefully
offline). Accepts both the internal gold schema (meta / metrics / sections /
canonical_entities / noise_tweets / sources) and the released participant
report, which carries only meta.schema_version and sections. Fields absent from
the participant view are simply not rendered.
"""
import json
import sys
from pathlib import Path

if len(sys.argv) < 2:
    sys.exit(__doc__)

in_path = Path(sys.argv[1])
out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else in_path.with_suffix(".html")

data = json.load(open(in_path))
payload = json.dumps(data, ensure_ascii=False)

html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ — Situation Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@75..100,400..800&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{
  --paper:#f6f5f1;
  --panel:#ffffff;
  --ink:#1e1c18;
  --ink-soft:#5c574d;
  --line:#dcd8cf;
  --accent:#8a4f0f;
  --accent-dark:#5c3406;
  --accent-wash:#f3e8d8;
  --confirmed:#2e6b3f;
  --confirmed-bg:#e4efe6;
  --potential:#8a6a0f;
  --potential-bg:#f4ecd2;
  --absent:#8a2f22;
  --absent-bg:#f5e2de;
  --mono:'IBM Plex Mono',ui-monospace,monospace;
  --serif:'Source Serif 4',Georgia,serif;
  --sans:'Archivo',system-ui,sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
body{background:var(--paper);color:var(--ink);font-family:var(--serif);font-size:16px;line-height:1.55}
a{color:var(--accent-dark)}
.wrap{max-width:1240px;margin:0 auto;padding:0 20px}

/* ---------- header ---------- */
header.masthead{border-bottom:3px solid var(--ink);background:var(--panel)}
.mast-inner{max-width:1240px;margin:0 auto;padding:34px 20px 0}
.stamp-row{display:flex;flex-wrap:wrap;gap:10px;align-items:center;font-family:var(--mono);font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-soft)}
.stamp{border:1px solid var(--line);padding:3px 9px;border-radius:2px;background:var(--paper)}
.stamp.accent{border-color:var(--accent);color:var(--accent-dark);background:var(--accent-wash)}
h1{font-family:var(--sans);font-stretch:80%;font-weight:760;font-size:clamp(30px,4.6vw,52px);line-height:1.04;letter-spacing:-.01em;margin:16px 0 8px;text-transform:uppercase}
.subtitle{font-family:var(--mono);font-size:13px;color:var(--ink-soft);margin-bottom:24px}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));border-top:1px solid var(--line)}
.metric{padding:14px 16px 16px;border-right:1px solid var(--line)}
.metric:last-child{border-right:none}
.metric .v{font-family:var(--sans);font-stretch:80%;font-weight:700;font-size:30px;color:var(--accent-dark)}
.metric .l{font-family:var(--mono);font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--ink-soft)}

/* ---------- layout ---------- */
.layout{display:grid;grid-template-columns:230px 1fr;gap:36px;padding:34px 0 90px}
nav.toc{position:sticky;top:18px;align-self:start;font-family:var(--sans);font-stretch:85%}
nav.toc .toc-title{font-family:var(--mono);font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-soft);margin-bottom:10px}
nav.toc a{display:flex;gap:9px;align-items:baseline;text-decoration:none;color:var(--ink-soft);padding:5px 8px;font-size:13.5px;border-left:2px solid transparent}
nav.toc a .num{font-family:var(--mono);font-size:11px;color:var(--accent);min-width:18px}
nav.toc a:hover{color:var(--ink);background:var(--panel)}
nav.toc a.active{color:var(--ink);border-left-color:var(--accent);background:var(--panel);font-weight:600}

/* ---------- sections ---------- */
section.sec{margin-bottom:44px;scroll-margin-top:14px}
.sec-head{display:flex;align-items:baseline;gap:14px;border-bottom:2px solid var(--ink);padding-bottom:6px;margin-bottom:16px}
.sec-head .num{font-family:var(--mono);font-size:13px;color:var(--accent-dark);background:var(--accent-wash);border:1px solid var(--accent);padding:1px 8px;border-radius:2px}
.sec-head h2{font-family:var(--sans);font-stretch:80%;font-weight:700;font-size:21px;text-transform:uppercase;letter-spacing:.01em}
.subsec{margin:0 0 18px}
.subsec h3{font-family:var(--sans);font-stretch:85%;font-weight:650;font-size:14.5px;color:var(--ink-soft);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px}
.subsec h3 .count{font-family:var(--mono);font-weight:400;color:var(--accent-dark)}
.empty-note{font-family:var(--mono);font-size:12px;color:var(--ink-soft);border:1px dashed var(--line);padding:8px 12px;background:var(--panel)}

/* bullets */
.bullet{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--line);padding:12px 14px;margin-bottom:8px;border-radius:0 3px 3px 0}
.bullet.confirmed{border-left-color:var(--confirmed)}
.bullet.potential{border-left-color:var(--potential)}
.bullet.absent{border-left-color:var(--absent)}
.bullet.announced,.bullet.background{border-left-color:var(--ink-soft)}
.b-meta{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:6px}
.bid{font-family:var(--mono);font-size:11px;color:var(--ink-soft)}
.badge{font-family:var(--mono);font-size:10.5px;letter-spacing:.05em;text-transform:uppercase;padding:1px 7px;border-radius:2px}
.badge.confirmed{color:var(--confirmed);background:var(--confirmed-bg)}
.badge.potential{color:var(--potential);background:var(--potential-bg)}
.badge.absent{color:var(--absent);background:var(--absent-bg)}
.badge.announced,.badge.background{color:var(--ink-soft);background:var(--paper);border:1px solid var(--line)}
.time-tag{font-family:var(--mono);font-size:11.5px;color:var(--accent-dark);background:var(--accent-wash);padding:1px 7px;border-radius:2px}
.rel-tag{font-family:var(--mono);font-size:10.5px;color:#fff;background:var(--ink);padding:1px 7px;border-radius:2px}
.b-text{font-size:15.5px}
.chips{margin-top:8px;display:flex;flex-wrap:wrap;gap:5px}
.chip{font-family:var(--mono);font-size:11px;color:var(--accent-dark);background:var(--paper);border:1px solid var(--line);padding:1px 7px;border-radius:10px;cursor:pointer;position:relative}
.chip:hover,.chip:focus-visible{border-color:var(--accent);background:var(--accent-wash)}
.chip:focus-visible{outline:2px solid var(--accent-dark);outline-offset:1px}
.rel-pair{margin-top:8px;display:grid;gap:5px;font-size:13px}
.rel-pair .ev{border-left:2px solid var(--line);padding:3px 10px;color:var(--ink-soft);font-style:italic}
.rel-pair .ev b{font-family:var(--mono);font-style:normal;font-size:10.5px;text-transform:uppercase;color:var(--ink);margin-right:6px}

/* timeline */
.timeline .bullet{position:relative;margin-left:130px}
.timeline .bullet .t-abs{position:absolute;left:-130px;top:12px;width:112px;text-align:right;font-family:var(--mono);font-size:11px;color:var(--accent-dark);line-height:1.4}
.timeline{position:relative}
.timeline:before{content:"";position:absolute;left:118px;top:4px;bottom:4px;width:1px;background:var(--line)}
@media(max-width:760px){
  .timeline .bullet{margin-left:0}
  .timeline .bullet .t-abs{position:static;width:auto;text-align:left;display:block;margin-bottom:4px}
  .timeline:before{display:none}
}

/* entities */
.entity-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px}
.entity{background:var(--panel);border:1px solid var(--line);padding:12px 14px;border-radius:3px}
.entity .e-head{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.entity .e-name{font-family:var(--sans);font-stretch:85%;font-weight:650;font-size:15px}
.entity .e-type{font-family:var(--mono);font-size:10.5px;text-transform:uppercase;color:var(--accent-dark);background:var(--accent-wash);padding:1px 6px;border-radius:2px;white-space:nowrap}
.entity .e-role{font-size:13px;color:var(--ink-soft);margin:5px 0}
.entity .e-alias{font-size:12.5px;color:var(--ink-soft)}
.entity .e-alias b{font-family:var(--mono);font-size:10.5px;text-transform:uppercase;color:var(--ink)}
.entity .e-foot{margin-top:7px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;font-family:var(--mono);font-size:10.5px;color:var(--ink-soft)}

/* sources */
.src-tools{display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap}
.src-tools input{font-family:var(--mono);font-size:13px;padding:7px 11px;border:1px solid var(--line);border-radius:3px;background:var(--panel);color:var(--ink);flex:1;min-width:220px}
.src-tools input:focus{outline:2px solid var(--accent);outline-offset:0;border-color:var(--accent)}
.src-list{max-height:520px;overflow-y:auto;border:1px solid var(--line);background:var(--panel);border-radius:3px}
.src-item{display:grid;grid-template-columns:64px 1fr;gap:10px;padding:8px 12px;border-bottom:1px solid var(--paper);scroll-margin-top:60px}
.src-item:last-child{border-bottom:none}
.src-item .sid{font-family:var(--mono);font-size:11.5px;color:var(--accent-dark)}
.src-item .stx{font-size:13.5px}
.src-item.flash{background:var(--accent-wash)}
.src-item.noise .sid{color:var(--absent)}
.smeta{display:block;margin-top:3px;font-size:11px;color:#8a8a8a}
.stime{margin-right:8px;font-variant-numeric:tabular-nums}
.sauthor{padding:1px 7px;border-radius:9px;background:#efece4;color:#6b6250;font-size:10.5px;text-transform:uppercase;letter-spacing:.4px}
.noise-label{font-family:var(--mono);font-size:10px;text-transform:uppercase;color:var(--absent);background:var(--absent-bg);padding:0 5px;border-radius:2px;margin-left:6px}

/* tooltip */
#tooltip{position:fixed;z-index:50;max-width:340px;background:var(--ink);color:#f3f0ea;font-size:12.5px;font-family:var(--serif);line-height:1.45;padding:9px 12px;border-radius:4px;pointer-events:none;opacity:0;transition:opacity .12s}
#tooltip.on{opacity:1}
#tooltip .tt-id{font-family:var(--mono);font-size:10px;color:#d9b98a;display:block;margin-bottom:3px;text-transform:uppercase;letter-spacing:.06em}

@media(max-width:920px){.layout{grid-template-columns:1fr}nav.toc{position:static;display:flex;flex-wrap:wrap;gap:2px}nav.toc .toc-title{width:100%}nav.toc a{border-left:none;border-bottom:2px solid transparent}nav.toc a.active{border-bottom-color:var(--accent)}}
</style>
</head>
<body>
<header class="masthead"><div class="mast-inner">
  <div class="stamp-row" id="stamps"></div>
  <h1 id="title"></h1>
  <div class="subtitle" id="subtitle"></div>
  <div class="metrics" id="metrics"></div>
</div></header>

<div class="wrap"><div class="layout">
  <nav class="toc" aria-label="Report sections"><div class="toc-title">Contents</div><div id="toc"></div></nav>
  <main id="main"></main>
</div></div>

<div id="tooltip" role="tooltip" aria-hidden="true"></div>

<script id="report-data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('report-data').textContent);
const tweetById = {};
// Internal gold files carry sources and noise_tweets; participant reports do
// not, since the tweets travel in a separate file. Both render.
(DATA.sources || []).forEach(s => tweetById[s.tweet_id] = s.summary);
const noiseIds = new Set((DATA.noise_tweets||[]).map(n => n.tweet_id));
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

/* header */
// Participant reports carry only schema_version, since title, hazard and
// window travel with the tweet file; internal gold files carry the rest.
const META = DATA.meta || {};
const TITLE = META.title || 'Situation report';
document.getElementById('title').textContent = TITLE;
document.getElementById('subtitle').textContent = META.subtitle || '';
document.title = TITLE + ' — Situation Report';
if (META.accent) {
  document.documentElement.style.setProperty('--accent', META.accent);
  document.documentElement.style.setProperty('--accent-dark', META.accent_dark);
}
document.getElementById('stamps').innerHTML =
  '<span class="stamp accent">Gold situation report</span>' +
  (META.dataset ? '<span class="stamp">dataset: ' + esc(META.dataset) + '</span>' : '') +
  (META.model ? '<span class="stamp">model: ' + esc(META.model) + '</span>' : '');
document.getElementById('metrics').innerHTML = (DATA.metrics || []).map(m =>
  '<div class="metric"><div class="v">' + esc(m.value) + '</div><div class="l">' + esc(m.label) + '</div></div>').join('');

/* helpers */
function chips(ids){
  if(!ids || !ids.length) return '';
  return '<div class="chips">' + ids.map(id =>
    '<button class="chip" data-tid="' + esc(id) + '" aria-label="Source tweet ' + esc(id) + '">#' + esc(id) + '</button>'
  ).join('') + '</div>';
}
function badge(conf){ return '<span class="badge ' + esc(conf) + '">' + esc(conf) + '</span>'; }

function bulletHTML(b, opts){
  opts = opts || {};
  let meta = '<span class="bid">' + esc(b.id) + '</span>' + badge(b.confidence);
  if(b.relation) meta += '<span class="rel-tag">' + esc(b.relation) + '</span>';
  let inner = '<div class="b-meta">' + meta + '</div><div class="b-text">' + esc(b.text) + '</div>';
  if(b.relation){
    inner += '<div class="rel-pair">' +
      '<div class="ev"><b>source</b>' + esc(b.source_event) + '</div>' +
      '<div class="ev"><b>target</b>' + esc(b.target_event) + '</div></div>';
  }
  inner += chips(b.tweet_ids);
  let pre = '';
  if(opts.timeline && b.time) pre = '<span class="t-abs">' + esc(b.time) + '</span>';
  return '<div class="bullet ' + esc(b.confidence) + '">' + pre + inner + '</div>';
}

/* sections */
const main = document.getElementById('main');
const toc = document.getElementById('toc');
let html = '';
DATA.sections.forEach(sec => {
  const anchor = 'sec-' + sec.id;
  toc.insertAdjacentHTML('beforeend',
    '<a href="#' + anchor + '" data-sec="' + anchor + '"><span class="num">' + esc(sec.id) + '</span>' + esc(sec.title) + '</a>');
  html += '<section class="sec" id="' + anchor + '"><div class="sec-head"><span class="num">' + esc(sec.id) + '</span><h2>' + esc(sec.title) + '</h2></div>';

  if(sec.id === '12'){
    html += '<div class="entity-grid">' + (DATA.canonical_entities || []).map(e =>
      '<div class="entity"><div class="e-head"><span class="e-name">' + esc(e.canonical) + '</span>' +
      '<span class="e-type">' + esc(e.type) + (e.subtype ? ' / ' + esc(e.subtype) : '') + '</span></div>' +
      '<div class="e-role">' + esc(e.role) + '</div>' +
      (e.aliases.length ? '<div class="e-alias"><b>aka</b> ' + e.aliases.map(esc).join(' · ') + '</div>' : '') +
      '<div class="e-foot"><span>' + e.mention_count + ' mentions</span><span>merge: ' + esc(e.merge_basis) + '</span></div>' +
      chips(e.tweet_ids) + '</div>').join('') + '</div>';
  } else {
    sec.subsections.forEach(ss => {
      const isTimeline = ss.bullets.some(b => b.time);
      html += '<div class="subsec"><h3>' + esc(ss.id) + ' · ' + esc(ss.title) +
              ' <span class="count">(' + ss.bullets.length + ')</span></h3>';
      if(!ss.bullets.length){
        html += '<div class="empty-note">No items recorded for this subsection in the source window.</div>';
      } else {
        html += '<div class="' + (isTimeline ? 'timeline' : '') + '">' +
                ss.bullets.map(b => bulletHTML(b, {timeline:isTimeline})).join('') + '</div>';
      }
      html += '</div>';
    });
    if(!sec.subsections.length) html += '<div class="empty-note">No subsections.</div>';
  }
  html += '</section>';
});

/* sources section */
toc.insertAdjacentHTML('beforeend', '<a href="#sec-src" data-sec="sec-src"><span class="num">S</span>Source tweets</a>');
html += '<section class="sec" id="sec-src"><div class="sec-head"><span class="num">S</span><h2>Source tweets</h2></div>' +
  '<div class="src-tools"><input id="src-filter" type="search" placeholder="Filter by id or text…" aria-label="Filter source tweets"></div>' +
  '<div class="src-list" id="src-list">' + (DATA.sources || []).map(s =>
    '<div class="src-item' + (noiseIds.has(s.tweet_id) ? ' noise' : '') + '" id="src-' + esc(s.tweet_id) + '">' +
    '<span class="sid">#' + esc(s.tweet_id) + (noiseIds.has(s.tweet_id) ? '<span class="noise-label">noise</span>' : '') + '</span>' +
    '<span class="stx">' + esc(s.summary) +
    (s.timestamp || s.author_type ? '<span class="smeta">' +
      (s.timestamp ? '<span class="stime">' + esc(s.timestamp.replace('T',' ').replace('Z',' UTC')) + '</span>' : '') +
      (s.author_type ? '<span class="sauthor sauthor-' + esc(s.author_type) + '">' + esc(s.author_type.replace('_',' ')) + '</span>' : '') +
    '</span>' : '') +
    '</span></div>').join('') + '</div></section>';

main.innerHTML = html;

/* tooltip + chip click */
const tt = document.getElementById('tooltip');
document.addEventListener('mouseover', e => {
  const c = e.target.closest('.chip');
  if(!c) return;
  const id = c.dataset.tid;
  tt.innerHTML = '<span class="tt-id">tweet #' + esc(id) + '</span>' + esc(tweetById[id] || 'not found in sources');
  tt.classList.add('on'); tt.setAttribute('aria-hidden','false');
});
document.addEventListener('mousemove', e => {
  if(!tt.classList.contains('on')) return;
  const pad = 14;
  let x = e.clientX + pad, y = e.clientY + pad;
  const r = tt.getBoundingClientRect();
  if(x + r.width > innerWidth - 8) x = e.clientX - r.width - pad;
  if(y + r.height > innerHeight - 8) y = e.clientY - r.height - pad;
  tt.style.left = x + 'px'; tt.style.top = y + 'px';
});
document.addEventListener('mouseout', e => {
  if(e.target.closest('.chip')){ tt.classList.remove('on'); tt.setAttribute('aria-hidden','true'); }
});
document.addEventListener('click', e => {
  const c = e.target.closest('.chip');
  if(!c) return;
  const el = document.getElementById('src-' + c.dataset.tid);
  if(!el) return;
  const filter = document.getElementById('src-filter');
  if(filter.value){ filter.value=''; filterSources(''); }
  el.scrollIntoView({behavior:'smooth', block:'center'});
  el.classList.add('flash');
  setTimeout(() => el.classList.remove('flash'), 1600);
});

/* source filter */
function filterSources(q){
  q = q.toLowerCase();
  document.querySelectorAll('.src-item').forEach(it => {
    it.style.display = it.textContent.toLowerCase().includes(q) ? '' : 'none';
  });
}
document.getElementById('src-filter').addEventListener('input', e => filterSources(e.target.value));

/* toc active state */
const links = [...toc.querySelectorAll('a')];
const obs = new IntersectionObserver(entries => {
  entries.forEach(en => {
    if(en.isIntersecting){
      links.forEach(l => l.classList.toggle('active', l.dataset.sec === en.target.id));
    }
  });
}, {rootMargin:'-10% 0px -70% 0px'});
document.querySelectorAll('section.sec').forEach(s => obs.observe(s));
</script>
</body>
</html>
"""

# Participant reports carry only schema_version in meta; internal gold files
# carry a title. Fall back to the file name so either renders.
_title = (data.get("meta") or {}).get("title") or Path(sys.argv[1]).stem
html = html.replace("__TITLE__", _title).replace("__DATA__", payload.replace("</", "<\\/"))
out_path.write_text(html)
print(f"Wrote {out_path} ({len(html):,} bytes) from {in_path}")
