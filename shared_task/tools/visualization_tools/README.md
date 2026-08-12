# Visualization tools

Two tools for inspecting the shared task data. Plain Python 3, no dependencies.

| Tool | Purpose |
| --- | --- |
| `view_cell.py` | Render one training pair as an HTML page: tweets and reference report side by side, linked by evidence. |
| `show_tweets.py` | Inspect tweets in the terminal, with filtering and a summary of the stream. |
| `sitrep2html.py` | Render a report on its own as a formatted document, with navigation. |

Layout:

```
shared_task/
├── data/
│   └── train/{crisis}/{crisis}.{window}.{replicate}.tweets.jsonl
└── tools/
    └── visualization_tools/
        ├── README.md
        ├── view_cell.py
        ├── show_tweets.py
        └── sitrep2html.py
```

Commands below are written to run from `shared_task/`. Both tools accept
absolute paths, so they can be run from anywhere.

---

## view_cell.py

Renders one pair as a single self-contained HTML file.

```bash
python3 tools/visualization_tools/view_cell.py data/train/volcano/volcano.W2.k1
```

The argument is the **cell stem**: the path without the `.tweets.jsonl` or
`.report.json` suffix. The tool reads both.

| Option | Effect |
| --- | --- |
| `-o OUT.html` | Write somewhere other than next to the input |
| `--open` | Open in a browser after writing (not available on remote servers) |

The page has tweets on the left and the reference report on the right.
**Selecting a statement illuminates the tweets that support it; selecting a
tweet illuminates the statements it supports.** Press Escape, or click the
background, to clear.

That relationship is the task. Comparing a `W1` report with the `W4` report for
the same crisis, and following the evidence links in each, is the fastest way
to see what a correct report contains and what it leaves out.

Test cells have no reference report. The tool renders the stream alone and says
so.

The output is one file with no external dependencies, so it can be opened
offline or sent to a colleague.

---

## show_tweets.py

Prints tweets in the terminal.

```bash
python3 tools/visualization_tools/show_tweets.py data/train/volcano/volcano.W1.k1.tweets.jsonl
```

| Option | Effect |
| --- | --- |
| `-n N` | Show at most N tweets (default 40; `0` for all) |
| `-s SOURCE` | Filter by source category; repeatable |
| `-g PATTERN` | Show only tweets whose text matches this regular expression |
| `--only-noise` | Show only off-topic tweets |
| `--stats` | Print a summary of the stream instead of the tweets |
| `--plain` | No color, no wrapping — for piping, logs, and notebooks |
| `-w N` | Wrap width |

Examples:

```bash
# what official accounts said about the rescue
python3 tools/visualization_tools/show_tweets.py data/train/ferry/ferry.W2.k1.tweets.jsonl \
    -s Government -g "rescued|missing"

# how the stream is composed
python3 tools/visualization_tools/show_tweets.py data/train/ferry/ferry.W2.k1.tweets.jsonl --stats
```

`--stats` reports the number of tweets, the proportion off topic, the share
carrying hashtags, mentions, URLs, retweet markers and figures, the breakdown
by source category, and the most frequent hashtags.

Source categories are `Government`, `Media`, `Eyewitness`, `NGOs`, `Outsiders`
and `Not labeled`. See `DATA_FORMAT.md`.

---

## sitrep2html.py

Renders a report on its own, without the tweets beside it.

```bash
python3 tools/visualization_tools/sitrep2html.py \
    data/train/volcano/volcano.W2.k1.report.json
```

The second argument is optional; without it the output is written next to the
input with an `.html` extension.

Where `view_cell.py` answers ``what in the tweets supports this statement'',
this answers ``what does the report say''. It lays the report out as a document
with a section navigator, so it is the better view for reading a report end to
end, comparing the same section across windows, or checking that your own
system output has the expected shape.

It accepts any file following the report schema, so it renders both the
reference reports and the reports your system produces. Fields the participant
view does not carry are simply omitted from the page.

The output is one self-contained file and opens offline.

---

## Which tool to use

| If you want to | Use |
| --- | --- |
| See what evidence supports a statement | `view_cell.py` |
| Read a report end to end | `sitrep2html.py` |
| Compare your output against the reference | `sitrep2html.py` on each |
| Search or filter the tweets | `show_tweets.py` |
| Check how a stream is composed | `show_tweets.py --stats` |

---

## Running in a notebook

Colab and Jupyter cannot open a browser, and terminal color codes do not render
in notebook output.

**View a pair inline:**

```python
import subprocess, html as _html
from IPython.display import HTML, display

STEM = "data/train/volcano/volcano.W2.k1"
subprocess.run(["python3", "tools/visualization_tools/view_cell.py", STEM, "-o", "/tmp/cell.html"],
               check=True)

page = open("/tmp/cell.html").read()
display(HTML(f'<iframe srcdoc="{_html.escape(page, quote=True)}" '
             f'width="100%" height="760" style="border:1px solid #ccd2d8"></iframe>'))
```

The iframe keeps the page's styles from mixing with the notebook and gives the
two columns their own scrolling.

**Browse cells with a picker:**

```python
import glob, os, subprocess, html as _html
import ipywidgets as w
from IPython.display import HTML, display

stems = sorted({p.rsplit(".tweets.jsonl", 1)[0]
                for p in glob.glob("data/train/*/*.tweets.jsonl")})
dd = w.Dropdown(options=[(os.path.basename(s), s) for s in stems],
                description="cell:", layout=w.Layout(width="420px"))
out = w.Output()

def show(_=None):
    subprocess.run(["python3", "tools/visualization_tools/view_cell.py", dd.value, "-o", "/tmp/cell.html"],
                   check=True)
    page = open("/tmp/cell.html").read()
    with out:
        out.clear_output()
        display(HTML(f'<iframe srcdoc="{_html.escape(page, quote=True)}" '
                     f'width="100%" height="760" style="border:1px solid #ccd2d8"></iframe>'))

dd.observe(show, names="value"); show()
display(dd, out)
```

**Print tweets in a notebook** — use `--plain`, or the output will contain
escape codes:

```python
!python3 tools/visualization_tools/show_tweets.py data/train/volcano/volcano.W1.k1.tweets.jsonl --plain -n 15
!python3 tools/visualization_tools/show_tweets.py data/train/volcano/volcano.W1.k1.tweets.jsonl --stats --plain
```

Both `view_cell.py` and `sitrep2html.py` produce standalone HTML and can be
displayed the same way.

**Download an HTML page to open locally** (Colab):

```python
from google.colab import files
files.download("/tmp/cell.html")
```

---

## Where to start

1. Render a `W1` cell and a `W4` cell for the same crisis.
2. In the `W1` page, select a few statements and look at what supports them.
3. Compare against `W4`: most statements the later report contains are absent
   from the earlier one, because the earlier tweets do not support them.

`DERIVATION_RULES.md` explains the rules that produce that difference.
