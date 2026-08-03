# Daily Tech News Dashboard

A local, self-contained AI/tech news dashboard. No server, no build step, no
pip installs -- Python 3.13 stdlib only. Running it produces a single
`dashboard.html` you open directly with `file://` in a browser.

## Running it

```bash
python3 refresh.py
```

This does everything in one shot:

1. Collects from every source in `sources.py` (RSS/Atom blogs, arXiv, Hugging
   Face daily papers, Hacker News).
2. Merges the results into `data/store.json`, keyed by a stable item id, so
   re-running never duplicates items -- it's safe to run as often as you
   like (e.g. from a daily cron job).
3. Rolls items older than 100 days out of the store.
4. Runs the dedupe/classify/score pipeline over the full store.
5. Renders `dashboard.html` and `data/health.json`.
6. Prints a per-source item-count / error table to stdout.

Then just open `dashboard.html` in a browser (double-click it, or
`open dashboard.html` on macOS). Everything -- data, CSS, JS -- is inlined
into that one file; nothing is fetched at view time.

A full run takes roughly 1.5-2 minutes, dominated by the ~30 serial arXiv
"accepted paper" queries (arXiv's API is shared/rate-limited, so those run
one at a time with a 3-second gap between requests) and the Hugging Face
100-day backfill (parallelized, but still ~100 HTTP requests).

## Adding a source

Edit `sources.py`. Every source is a dict:

```python
{"name": "...", "url": "...", "kind": "rss", "tier": 0.7, "categories": ["innovation"]}
```

- `kind` must be one of `rss`, `arxiv`, `hf_papers`, `hn` -- `collect.py`
  dispatches on this.
- `tier` controls both the "how much do we trust this source" score
  component and the default sort within a dedup cluster (the highest-tier
  item in a cluster becomes the card you see; the rest show up as
  `also_covered_by`). Convention used here: `1.0` for primary lab/research
  sources (OpenAI, DeepMind, arXiv, HF papers, etc.), `0.7` for quality
  press/analysis, `0.4` for aggregator volume (HN, MarkTechPost).
- `categories` is just a hint; the real per-item classification happens in
  `score.classify()` regardless of where the item came from.

For a new `arxiv` accepted-venue query, add an entry with a `"venue"` key --
`collect.fetch_arxiv` will filter its `co:` hits to genuinely accepted
papers (see below) and tag the item with that venue name.

## How dedup, classification, and scoring work

**Dedup** (`score.dedupe`): two passes. First, exact canonical-URL matches
(same URL, or same arXiv/HF paper id, reported by more than one source) are
merged directly. Second, a title-similarity pass (Jaccard >= 0.6 over
stopword-stripped tokens, blocked by an inverted index so it doesn't degrade
to O(n^2) on the full corpus) catches the same press story covered under
slightly different headlines by different outlets. That second pass is
deliberately restricted to non-paper items -- research papers are already
almost entirely deduped by the URL pass, and fuzzy-matching thousands of
paper titles would be expensive for little benefit. Within a cluster, the
highest-tier item becomes the card shown; the other sources are recorded in
`also_covered_by`, and `len(also_covered_by)` itself feeds into the score
(more independent sources covering something is a signal it matters).

**Classification** (`score.classify`): multi-label, via keyword regex over
title + summary. `agentic` matches on agent/tool-use/MCP/orchestration/etc.
`papers` is automatic for anything from `arxiv`/`hf_papers`, or for press
items that both link to arxiv.org and explicitly discuss a
"paper"/"study"/"research". `innovation` is the fallback bucket applied only
when neither of the above matched -- an agentic-AI paper still shows up
under both the Papers and Agentic AI tabs.

**Scoring** (`score.score`): `tier + HN-points term + HF-upvotes term +
0.5*(sources_in_cluster - 1) + 0.6 if accepted-at-a-top-tier-venue +
recency_decay`. `recency_decay` is an exponential half-life of 10 days,
included for the Today/7-day/30-day views (`score_daily`) but *excluded*
from the 3-month "significance" view (`score_significance`), so that view
can surface older-but-bigger stories instead of just whatever is freshest.

## Known limitation: 3-month view depth on day one

RSS/Atom feeds only expose their most recent entries (no historical
date-range query support), so on a fresh checkout the 3-month press-coverage
picture is thin -- it only has whatever each feed happened to be showing at
first-run time. It fills in properly as `refresh.py` is run daily and each
day's items accumulate in `data/store.json`. arXiv and Hugging Face daily
papers, and Hacker News, don't have this problem -- their APIs support real
date-range/day-by-day queries, so those three sources are backfilled with
genuine 100-day depth from the very first run. The dashboard's 3-month tab
shows a note about this in the UI.

## Files

- `sources.py` -- the source registry.
- `collect.py` -- `fetch(source)` per source kind, plus `collect_all()`
  orchestration (parallel RSS/HN, serial rate-limited arXiv, parallel HF
  day-walk), with per-source timeout/retry and a health dict that a failing
  source can never crash out of.
- `score.py` -- `normalize()` / `dedupe()` / `classify()` / `score()`.
- `render.py` -- turns a list of scored items + the health dict into the
  single self-contained `dashboard.html` string.
- `refresh.py` -- the orchestrator described above; both `data/store.json`
  and `dashboard.html` are written atomically (write to a `.tmp` file, then
  `os.replace()`) so a crash mid-run can't leave a corrupt file.
- `deploy.py` -- copies `dashboard.html` to `index.html` and commits/pushes
  it (and `summary.json`, if present), publishing to GitHub Pages.
  Fast-forwards to `origin/main` first so it tolerates being run from two
  places (see below) without a rejected push.
- `data/store.json` / `data/health.json` -- persistent state (git-ignorable;
  regenerated by `refresh.py`).
- `summary.json` -- optional, repo-root (not gitignored, unlike `data/`), AI-written
  daily narrative summary. See "AI summary" below.

## AI summary

The dashboard has an optional "Today's AI Summary" section above the hero
strip -- a short narrative (not a list) synthesizing the day's most
significant stories, written by Claude rather than the deterministic scoring
pipeline. It reads from `summary.json` at the repo root:

```json
{"generated_at": "2026-08-04T02:35:00+00:00", "text": "paragraph one\n\nparagraph two", "item_count": 12}
```

`refresh.py` loads this file (if present) and embeds it in `dashboard.html`;
`python3 refresh.py --render-only` re-renders from the existing store and
summary without re-collecting from any source -- useful right after writing
a fresh `summary.json` so you don't pay the ~2-minute full-collection cost
just to pick it up.

**This file is only ever written by Claude** -- either via the `refresh`
skill (`.claude/skills/refresh/`, run on demand with `/refresh`) or the local
`daily-tech-news` scheduled task, both of which run the identical sequence.
It is never written by `refresh.py`/`deploy.py` themselves, and never by the
GitHub Actions workflow, which runs unattended with no Claude available to
draft the narrative. That means the AI summary only updates when a human (or
the schedule) actually triggers one of those two paths; on GitHub-Actions-only
refreshes the rest of the dashboard stays current but the summary section is
unchanged from whenever it was last written. The UI shows the summary's
generation timestamp right in its heading and flags it once it's more than
~36 hours old, so this is visible rather than silent. No `summary.json` at
all (e.g. first run) shows a placeholder explaining why.

Because this genuinely requires an LLM to write, and this project intentionally
has no Anthropic API key wired in (see the Hosting section), there is no
automated path to keep it fresh independent of a Claude session actually
running the refresh skill or scheduled task.

## Hosting and automatic refresh

Published at **https://anishpawar.github.io/daily-tech-update/** via GitHub
Pages, serving `index.html` from the `main` branch root.

Three independent things can trigger a refresh:

1. **`.github/workflows/refresh.yml`** -- runs on GitHub's own servers, on a
   daily schedule (`cron: "31 2 * * *"`, ~08:01 IST) and on-demand via
   `workflow_dispatch` (trigger it from the repo's Actions tab on GitHub, or
   `gh workflow run refresh.yml`). Uses the repo's built-in `GITHUB_TOKEN` to
   push, so no secrets need managing. Runs `refresh.py` then `deploy.py` --
   content only, no AI summary (see above). This is what makes the dashboard
   self-updating independent of this Mac being on or any local automation
   running.
2. The **`refresh` skill** (`.claude/skills/refresh/SKILL.md`) -- run
   on-demand with `/refresh` in a Claude Code session in this project. Runs
   the full pipeline including the AI summary (`refresh.py` → write
   `summary.json` → `refresh.py --render-only` → `deploy.py`).
3. The local **`daily-tech-news` Claude scheduled task** runs the identical
   sequence as the `refresh` skill, automatically, on this Mac -- redundant
   with (1) for the content but the only automated path that also refreshes
   the AI summary. `deploy.py`'s fast-forward step keeps all three from
   stepping on each other.
