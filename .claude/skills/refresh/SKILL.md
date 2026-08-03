---
name: refresh
description: Refresh the Daily Tech News Dashboard -- re-collect from all ~55 sources, write a fresh AI summary of today's most significant stories, re-render, and publish to GitHub Pages. Use whenever the user asks to refresh, update, or regenerate the daily tech news dashboard, or invokes /refresh while working in ~/code/daily_tech_update.
---

# Refresh the Daily Tech News Dashboard

Full pipeline for `~/code/daily_tech_update`: collect → score → AI summary → render → publish.
This performs the same sequence as the automated `daily-tech-news` scheduled task, so it can be
run manually anytime instead of waiting for the next scheduled run.

## Steps

1. Run `python3 refresh.py` from `~/code/daily_tech_update` (stdlib-only, no pip installs). This
   fetches all sources (arXiv, Hugging Face daily papers, Hacker News, ~17 AI/tech RSS feeds),
   dedupes/scores/classifies them, merges into `data/store.json`, and regenerates
   `dashboard.html`. Takes roughly 1.5-2 minutes, dominated by rate-limited arXiv queries.

2. Read `data/health.json` (per-source `{ok, count, error, last_run}`). If any source has been
   failing for multiple runs in a row, flag it by name when reporting back.

3. Write today's AI summary:
   - Read `data/store.json` (a JSON object keyed by item id; each entry has `title`, `url`,
     `source`, `tier`, `published` (ISO timestamp), `summary`, `raw_kind`, `comment` (arXiv venue
     info when relevant), `signals` (may contain `hn_points`, `hn_comments`, `hf_upvotes`, `venue`)).
   - Filter to entries whose `published` falls in the last 24 hours. If fewer than 5 such entries
     exist, widen to the last 48 hours.
   - From those, using `tier` (1.0 = primary lab/research source, 0.7 = quality press, 0.4 =
     aggregator), `signals.hn_points` / `signals.hf_upvotes` (traction), and whether `comment`
     shows an accepted top-tier venue, identify the roughly 8-15 most significant stories across
     AI/tech innovation, notable research papers, and agentic AI.
   - Write 3-5 short paragraphs (a real narrative, not a bullet list) synthesizing what actually
     happened, in plain direct prose -- no "In today's fast-moving world of AI..." filler. Name
     specific things (models, paper results, company actions) rather than vague generalities. If a
     theme genuinely has no news that period (e.g. no accepted-paper news broke), say so plainly
     rather than forcing an item in.
   - Save to `summary.json` at the **repo root** (not under `data/`) with exactly this schema:
     ```json
     {"generated_at": "<current UTC time, ISO 8601, e.g. 2026-08-04T02:35:00+00:00>", "text": "<paragraph 1>\n\n<paragraph 2>\n\n<paragraph 3>", "item_count": <number of items drawn on>}
     ```
     Use a real Write tool call with actual JSON -- paragraphs separated by a blank line inside `text`.

4. Run `python3 refresh.py --render-only` to bake the new summary into `dashboard.html` without
   re-fetching every source. (This step is only needed because step 1 already ran and rendered
   once before the summary existed -- it re-renders from the now-current store + summary.)

5. Run `python3 deploy.py`. This copies `dashboard.html` to `index.html`, and commits+pushes both
   `index.html` and `summary.json` to the `daily-tech-update` GitHub repo (origin/main -- gh CLI
   should already be authenticated). It fast-forwards to `origin/main` first and no-ops cleanly if
   there's nothing new to publish. If it reports a failed fast-forward or rejected push (can happen
   if GitHub Actions published in between), resolve it with a normal `git fetch` + `git merge
   origin/main` -- the only likely conflict is on `index.html`/`dashboard.html`, which are fully
   generated; resolve by keeping the local version (it was just regenerated from the current data)
   and re-copying `dashboard.html` to `index.html` before completing the merge commit. Do not
   force-push.

6. Report back: today's top few stories, the "N/M sources healthy" count, and whether publish
   succeeded (deploy.py's own stdout says so).

## Notes

- The published page is live at https://anishpawar.github.io/daily-tech-update/
- `.github/workflows/refresh.yml` also runs this same content pipeline on a daily schedule and via
  manual dispatch on GitHub's own servers, but it does **not** write `summary.json` -- there's no
  Claude available in that unattended context to draft the narrative. The AI summary only updates
  when this skill (or the local scheduled task) actually runs.
- Do not modify any of the project's Python files as part of a routine refresh -- just run the
  steps above.
