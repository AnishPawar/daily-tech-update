"""
render(items, health) -> str

Produces one complete, self-contained HTML document (no external CDN/font/
image dependencies -- inline <style>/<script>). Item data is embedded as
JSON in a <script type="application/json" id="feed-data"> tag; all
filtering/sorting/search happens client-side in vanilla JS.
"""

import json
from datetime import datetime, timezone

CATEGORY_LABELS = {
    "innovation": "AI & Tech Innovation",
    "papers": "Papers",
    "agentic": "Agentic AI",
}


def _iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _serialize_item(it):
    signals = it.get("signals", {}) or {}
    return {
        "id": it.get("id"),
        "title": it.get("title", ""),
        "url": it.get("url", ""),
        "source": it.get("source", ""),
        "tier": it.get("tier", 0.4),
        "published": _iso(it.get("published")),
        "summary": it.get("summary", ""),
        "raw_kind": it.get("raw_kind", ""),
        "categories": it.get("categories", []) or [],
        "also_covered_by": it.get("also_covered_by", []) or [],
        "cluster_size": it.get("cluster_size", 1),
        "hn_points": signals.get("hn_points"),
        "hn_comments": signals.get("hn_comments"),
        "hf_upvotes": signals.get("hf_upvotes"),
        "venue": signals.get("venue"),
        "score_daily": round(it.get("score_daily", 0.0), 4),
        "score_significance": round(it.get("score_significance", 0.0), 4),
    }


def render(items, health, generated_at=None, summary=None):
    if generated_at is None:
        generated_at = datetime.now(timezone.utc)

    payload = {
        "generated_at": _iso(generated_at),
        "items": [_serialize_item(it) for it in items],
        "health": health or {},
        "summary": summary or None,
    }

    failed_sources = sorted(name for name, h in (health or {}).items() if not h.get("ok"))
    ok_count = sum(1 for h in (health or {}).values() if h.get("ok"))
    total_sources = len(health or {})

    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # Guard against `</script>` inside the JSON breaking the surrounding tag.
    payload_json = payload_json.replace("</", "<\\/")

    html = _TEMPLATE.replace("__FEED_DATA_JSON__", payload_json)
    html = html.replace("__GENERATED_AT_HUMAN__", generated_at.strftime("%Y-%m-%d %H:%M UTC"))
    html = html.replace("__OK_COUNT__", str(ok_count))
    html = html.replace("__TOTAL_SOURCES__", str(total_sources))
    if failed_sources:
        note = (
            f'<span class="health-bad">{len(failed_sources)} source'
            f'{"s" if len(failed_sources) != 1 else ""} unavailable: '
            f'{", ".join(failed_sources)}</span>'
        )
    else:
        note = '<span class="health-ok">All sources healthy</span>'
    html = html.replace("__HEALTH_NOTE__", note)
    return html


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily Tech News Dashboard</title>
<style>
:root {
  --bg: #f5f6f8;
  --panel: #ffffff;
  --text: #1a1d23;
  --muted: #5b6270;
  --border: #e1e4e9;
  --accent: #2f6fed;
  --accent-bg: #e8f0ff;
  --chip-bg: #eef0f4;
  --chip-active-bg: #2f6fed;
  --chip-active-text: #ffffff;
  --tag-innovation: #2f6fed;
  --tag-papers: #8a3ffc;
  --tag-agentic: #0f9d58;
  --danger: #c0392b;
  --ok: #0f9d58;
  --shadow: 0 1px 3px rgba(20,20,30,0.08), 0 1px 2px rgba(20,20,30,0.06);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14161a;
    --panel: #1c1f26;
    --text: #eceef2;
    --muted: #9aa1ae;
    --border: #2b2f38;
    --accent: #6ea1ff;
    --accent-bg: #1c2b4d;
    --chip-bg: #262a33;
    --chip-active-bg: #6ea1ff;
    --chip-active-text: #0c1220;
    --tag-innovation: #6ea1ff;
    --tag-papers: #c9a3ff;
    --tag-agentic: #4fd18b;
    --danger: #ff7a6e;
    --ok: #4fd18b;
    --shadow: 0 1px 3px rgba(0,0,0,0.4), 0 1px 2px rgba(0,0,0,0.3);
  }
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.4;
  min-height: 100vh;
}
a { color: inherit; }
.wrap { max-width: 1180px; margin: 0 auto; padding: 20px 16px 60px; }

header.top {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 18px;
}
header.top h1 { font-size: 1.5rem; margin: 0; }
header.top .subtitle { color: var(--muted); font-size: 0.85rem; }
header.top .top-right { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; }
.refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--text);
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 500;
  text-decoration: none;
  box-shadow: var(--shadow);
}
.refresh-btn:hover { border-color: var(--accent); color: var(--accent); }

/* AI summary */
.ai-summary {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px 18px;
  margin-bottom: 22px;
  box-shadow: var(--shadow);
}
.ai-summary h2 {
  font-size: 0.85rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  margin: 0 0 10px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.ai-summary .badge-ai {
  background: var(--accent-bg);
  color: var(--accent);
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  text-transform: none;
  padding: 2px 8px;
  border-radius: 999px;
}
.ai-summary p { margin: 0 0 10px; font-size: 0.92rem; line-height: 1.55; }
.ai-summary p:last-child { margin-bottom: 0; }
.ai-summary .stale-note, .ai-summary .empty-note {
  color: var(--muted);
  font-size: 0.78rem;
  margin-top: 10px;
}

/* Hero strip */
.hero { margin-bottom: 26px; }
.hero h2 { font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin: 0 0 10px; }
.hero-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 10px;
}
.hero-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 100px;
}
.hero-card a.title { font-weight: 600; font-size: 0.92rem; text-decoration: none; }
.hero-card a.title:hover { text-decoration: underline; }
.hero-card .meta { color: var(--muted); font-size: 0.75rem; }
.hero-empty { color: var(--muted); font-size: 0.85rem; }

/* Controls */
.controls {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px;
  margin-bottom: 18px;
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.segmented {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
.segmented button {
  border: none;
  background: var(--panel);
  color: var(--text);
  padding: 7px 14px;
  font-size: 0.85rem;
  cursor: pointer;
  border-right: 1px solid var(--border);
}
.segmented button:last-child { border-right: none; }
.segmented button.active { background: var(--accent); color: #fff; }

.tabs { display: inline-flex; flex-wrap: wrap; gap: 6px; }
.tabs button {
  border: 1px solid var(--border);
  background: var(--chip-bg);
  color: var(--text);
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 0.82rem;
  cursor: pointer;
}
.tabs button.active { background: var(--chip-active-bg); color: var(--chip-active-text); border-color: transparent; }

#search {
  flex: 1 1 220px;
  min-width: 180px;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text);
  font-size: 0.88rem;
}
#search:focus { outline: 2px solid var(--accent); outline-offset: 1px; }

.source-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 96px;
  overflow-y: auto;
  padding: 2px;
}
.source-chip {
  border: 1px solid var(--border);
  background: var(--chip-bg);
  color: var(--muted);
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 0.76rem;
  cursor: pointer;
  white-space: nowrap;
}
.source-chip.active { background: var(--chip-active-bg); color: var(--chip-active-text); border-color: transparent; }

.notice { color: var(--muted); font-size: 0.78rem; }

/* Results */
#result-count { color: var(--muted); font-size: 0.8rem; margin: 0 0 10px; }
#results {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}
.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px;
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.card .title { font-weight: 600; font-size: 0.95rem; text-decoration: none; }
.card .title:hover { text-decoration: underline; }
.card .meta-row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 0.74rem; color: var(--muted); }
.badge-source {
  background: var(--chip-bg);
  border-radius: 6px;
  padding: 2px 7px;
  font-weight: 500;
}
.cats { display: flex; flex-wrap: wrap; gap: 5px; }
.cat-tag {
  font-size: 0.7rem;
  padding: 2px 8px;
  border-radius: 999px;
  color: #fff;
  font-weight: 600;
}
.cat-innovation { background: var(--tag-innovation); }
.cat-papers { background: var(--tag-papers); }
.cat-agentic { background: var(--tag-agentic); }
.signal-chips { display: flex; flex-wrap: wrap; gap: 5px; }
.signal-chip {
  font-size: 0.72rem;
  background: var(--accent-bg);
  color: var(--accent);
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 600;
}
.summary {
  font-size: 0.82rem;
  color: var(--text);
  opacity: 0.9;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.no-results { color: var(--muted); padding: 30px 0; text-align: center; }

footer.foot {
  margin-top: 30px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
  font-size: 0.78rem;
  color: var(--muted);
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: space-between;
}
.health-ok { color: var(--ok); }
.health-bad { color: var(--danger); }

kbd {
  background: var(--chip-bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 0 5px;
  font-size: 0.72rem;
}

@media (max-width: 560px) {
  header.top h1 { font-size: 1.25rem; }
  .segmented button { padding: 6px 10px; font-size: 0.8rem; }
}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div>
      <h1>Daily Tech News Dashboard</h1>
      <div class="subtitle">AI &amp; tech news, ranked across research, agentic AI, and innovation</div>
    </div>
    <div class="top-right">
      <a class="refresh-btn" href="https://github.com/AnishPawar/daily-tech-update/actions/workflows/refresh.yml" target="_blank" rel="noopener noreferrer" title="Opens this dashboard's GitHub Actions workflow -- click &quot;Run workflow&quot; there to refresh now">&#8635; Refresh</a>
      <div class="subtitle">Generated __GENERATED_AT_HUMAN__ &middot; __OK_COUNT__/__TOTAL_SOURCES__ sources healthy</div>
    </div>
  </header>

  <section class="ai-summary" id="ai-summary"></section>

  <section class="hero">
    <h2>Today's Top Stories</h2>
    <div class="hero-grid" id="hero-grid"></div>
  </section>

  <section class="controls">
    <div class="row">
      <div class="segmented" id="range-tabs">
        <button data-range="1" class="active">Today <kbd>1</kbd></button>
        <button data-range="7">7 days <kbd>2</kbd></button>
        <button data-range="30">30 days <kbd>3</kbd></button>
        <button data-range="90">3 months <kbd>4</kbd></button>
      </div>
      <input id="search" type="text" placeholder="Search titles, summaries, sources...  (press / to focus)">
    </div>
    <div class="row">
      <div class="tabs" id="category-tabs">
        <button data-cat="all" class="active">All</button>
        <button data-cat="innovation">AI &amp; Tech Innovation</button>
        <button data-cat="papers">Papers</button>
        <button data-cat="agentic">Agentic AI</button>
      </div>
    </div>
    <div class="row">
      <div class="source-chips" id="source-chips"></div>
    </div>
    <div class="notice" id="range-notice" style="display:none;">
      3-month view is sorted by overall significance (no recency weighting) and capped to ~40 stories.
      Press coverage backfill is limited on day one -- RSS feeds only expose recent entries, so this view
      fills in with real depth as the dashboard is run daily. Papers and Hacker News are backfilled properly
      from day one since those APIs support real date-range queries.
    </div>
  </section>

  <p id="result-count"></p>
  <div id="results"></div>

  <footer class="foot">
    <div>Last updated: __GENERATED_AT_HUMAN__</div>
    <div>__HEALTH_NOTE__</div>
  </footer>
</div>

<script type="application/json" id="feed-data">__FEED_DATA_JSON__</script>
<script>
(function () {
  "use strict";
  var payload = JSON.parse(document.getElementById("feed-data").textContent);
  var ITEMS = payload.items || [];
  var SUMMARY = payload.summary || null;
  var CAT_LABELS = { innovation: "AI & Tech Innovation", papers: "Papers", agentic: "Agentic AI" };

  var state = { range: 1, category: "all", sources: new Set(), search: "" };

  var allSources = Array.from(new Set(ITEMS.map(function (it) { return it.source; }))).sort();

  function fmtDate(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }

  function within(iso, days) {
    if (!iso) return false;
    var d = new Date(iso).getTime();
    if (isNaN(d)) return false;
    var cutoff = Date.now() - days * 86400000;
    return d >= cutoff;
  }

  function escapeHtml(s) {
    return (s || "").replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function signalChips(it) {
    var chips = [];
    if (it.hn_points) chips.push('<span class="signal-chip">&#9650; ' + it.hn_points + ' HN</span>');
    if (it.hf_upvotes) chips.push('<span class="signal-chip">&#9650; ' + it.hf_upvotes + ' HF</span>');
    if (it.cluster_size && it.cluster_size > 1) chips.push('<span class="signal-chip">' + it.cluster_size + ' sources</span>');
    if (it.venue) chips.push('<span class="signal-chip">' + escapeHtml(it.venue) + '</span>');
    return chips.join("");
  }

  function catTags(it) {
    return (it.categories || []).map(function (c) {
      return '<span class="cat-tag cat-' + c + '">' + (CAT_LABELS[c] || c) + "</span>";
    }).join("");
  }

  function cardHtml(it) {
    var title = escapeHtml(it.title);
    var summary = escapeHtml(it.summary || "");
    return (
      '<article class="card">' +
        '<a class="title" href="' + escapeHtml(it.url) + '" target="_blank" rel="noopener noreferrer">' + title + "</a>" +
        '<div class="meta-row">' +
          '<span class="badge-source">' + escapeHtml(it.source) + "</span>" +
          '<span>' + fmtDate(it.published) + "</span>" +
        "</div>" +
        '<div class="cats">' + catTags(it) + "</div>" +
        '<div class="signal-chips">' + signalChips(it) + "</div>" +
        (summary ? '<div class="summary">' + summary + "</div>" : "") +
      "</article>"
    );
  }

  function renderSummary() {
    var el = document.getElementById("ai-summary");
    if (!SUMMARY || !SUMMARY.text) {
      el.innerHTML =
        '<h2>Today\'s AI Summary <span class="badge-ai">AI</span></h2>' +
        '<div class="empty-note">Not generated yet -- this is written by Claude as part of the daily scheduled task ' +
        '(only runs when that task fires, so it can lag behind the deterministic dashboard below).</div>';
      return;
    }
    var paragraphs = String(SUMMARY.text).split(/\n\s*\n/).filter(function (p) { return p.trim(); });
    var html = '<h2>Today\'s AI Summary <span class="badge-ai">AI</span></h2>';
    html += paragraphs.map(function (p) { return "<p>" + escapeHtml(p.trim()) + "</p>"; }).join("");

    var genAt = SUMMARY.generated_at ? new Date(SUMMARY.generated_at) : null;
    if (genAt && !isNaN(genAt.getTime())) {
      var ageHours = (Date.now() - genAt.getTime()) / 3600000;
      var whenText = genAt.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
      if (ageHours > 36) {
        html += '<div class="stale-note">Written ' + whenText + ' -- more than a day ago. The AI summary only refreshes when the local scheduled task runs; the dashboard below is still current.</div>';
      } else {
        html += '<div class="stale-note">Written ' + whenText + '</div>';
      }
    }
    el.innerHTML = html;
  }

  function renderHero() {
    var pool = ITEMS.filter(function (it) { return within(it.published, 1); });
    pool.sort(function (a, b) { return b.score_daily - a.score_daily; });
    var top = pool.slice(0, 5);
    var el = document.getElementById("hero-grid");
    if (!top.length) {
      el.innerHTML = '<div class="hero-empty">No stories published in the last 24 hours yet -- check the 7-day or 30-day view.</div>';
      return;
    }
    el.innerHTML = top.map(function (it) {
      return (
        '<div class="hero-card">' +
          '<a class="title" href="' + escapeHtml(it.url) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(it.title) + "</a>" +
          '<div class="meta">' + escapeHtml(it.source) + " &middot; " + fmtDate(it.published) + "</div>" +
          '<div class="signal-chips">' + signalChips(it) + "</div>" +
        "</div>"
      );
    }).join("");
  }

  function renderSourceChips() {
    var el = document.getElementById("source-chips");
    el.innerHTML = allSources.map(function (s) {
      return '<button class="source-chip" data-src="' + escapeHtml(s) + '">' + escapeHtml(s) + "</button>";
    }).join("");
    Array.prototype.forEach.call(el.querySelectorAll(".source-chip"), function (btn) {
      btn.addEventListener("click", function () {
        var s = btn.getAttribute("data-src");
        if (state.sources.has(s)) { state.sources.delete(s); btn.classList.remove("active"); }
        else { state.sources.add(s); btn.classList.add("active"); }
        renderResults();
      });
    });
  }

  function renderResults() {
    var days = state.range;
    var significance = days === 90;
    var pool = ITEMS.filter(function (it) { return within(it.published, days); });

    if (state.category !== "all") {
      pool = pool.filter(function (it) { return (it.categories || []).indexOf(state.category) !== -1; });
    }
    if (state.sources.size) {
      pool = pool.filter(function (it) { return state.sources.has(it.source); });
    }
    if (state.search) {
      var q = state.search.toLowerCase();
      pool = pool.filter(function (it) {
        return (it.title || "").toLowerCase().indexOf(q) !== -1 ||
               (it.summary || "").toLowerCase().indexOf(q) !== -1 ||
               (it.source || "").toLowerCase().indexOf(q) !== -1;
      });
    }

    pool.sort(function (a, b) {
      return significance ? (b.score_significance - a.score_significance) : (b.score_daily - a.score_daily);
    });
    if (significance) pool = pool.slice(0, 40);

    document.getElementById("range-notice").style.display = significance ? "block" : "none";
    document.getElementById("result-count").textContent = pool.length + " stor" + (pool.length === 1 ? "y" : "ies");

    var el = document.getElementById("results");
    el.innerHTML = pool.length ? pool.map(cardHtml).join("") : '<div class="no-results">No stories match the current filters.</div>';
  }

  function setRange(r) {
    state.range = r;
    Array.prototype.forEach.call(document.querySelectorAll("#range-tabs button"), function (btn) {
      btn.classList.toggle("active", Number(btn.getAttribute("data-range")) === r);
    });
    renderResults();
  }

  function setCategory(c) {
    state.category = c;
    Array.prototype.forEach.call(document.querySelectorAll("#category-tabs button"), function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-cat") === c);
    });
    renderResults();
  }

  document.getElementById("range-tabs").addEventListener("click", function (e) {
    var btn = e.target.closest("button[data-range]");
    if (btn) setRange(Number(btn.getAttribute("data-range")));
  });
  document.getElementById("category-tabs").addEventListener("click", function (e) {
    var btn = e.target.closest("button[data-cat]");
    if (btn) setCategory(btn.getAttribute("data-cat"));
  });
  document.getElementById("search").addEventListener("input", function (e) {
    state.search = e.target.value;
    renderResults();
  });

  document.addEventListener("keydown", function (e) {
    var active = document.activeElement;
    var typing = active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA");
    if (e.key === "/" && !typing) {
      e.preventDefault();
      document.getElementById("search").focus();
      return;
    }
    if (typing) return;
    if (["1", "2", "3", "4"].indexOf(e.key) !== -1) {
      var map = { "1": 1, "2": 7, "3": 30, "4": 90 };
      setRange(map[e.key]);
    }
  });

  renderSummary();
  renderHero();
  renderSourceChips();
  renderResults();
})();
</script>
</body>
</html>
"""
