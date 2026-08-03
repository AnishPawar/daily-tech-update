"""
Orchestrator for the Daily Tech News Dashboard.

    python3 refresh.py

Collects from every source in sources.py, merges new items into
data/store.json (keyed by item id so re-running is idempotent), rolls off
items older than 100 days, runs the dedupe/classify/score pipeline over the
full store, renders dashboard.html, and writes data/health.json. Both
data/store.json and dashboard.html are written atomically (write to a .tmp
sibling, then os.replace()) so a crash mid-run never leaves a half-written
file. Prints a per-source summary table to stdout.
"""

import json
import os
from datetime import datetime, timedelta, timezone

import collect
import render
import score
import sources

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
STORE_PATH = os.path.join(DATA_DIR, "store.json")
HEALTH_PATH = os.path.join(DATA_DIR, "health.json")
DASHBOARD_PATH = os.path.join(BASE_DIR, "dashboard.html")

ROLLOFF_DAYS = 100


# ---------------------------------------------------------------------------
# Atomic writes
# ---------------------------------------------------------------------------

def _atomic_write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _atomic_write_text(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Store <-> Item conversion
# ---------------------------------------------------------------------------

def _load_store():
    if not os.path.exists(STORE_PATH):
        return {}
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _item_to_store_entry(item, now_iso):
    published = item.get("published")
    published_iso = published.isoformat() if isinstance(published, datetime) else published
    return {
        "id": item["id"],
        "canonical_url": item["canonical_url"],
        "title": item["title"],
        "url": item["url"],
        "source": item["source"],
        "source_url": item.get("source_url", ""),
        "tier": item["tier"],
        "published": published_iso,
        "summary": item.get("summary", ""),
        "raw_kind": item.get("raw_kind", ""),
        "comment": item.get("comment", ""),
        "signals": item.get("signals", {}),
        "first_seen": item.get("first_seen") or now_iso,
        "last_seen": now_iso,
    }


def _store_entry_to_item(entry):
    return {
        "id": entry["id"],
        "canonical_url": entry["canonical_url"],
        "title": entry["title"],
        "url": entry["url"],
        "source": entry["source"],
        "source_url": entry.get("source_url", ""),
        "tier": entry.get("tier", 0.4),
        "published": score._parse_dt(entry.get("published")),
        "summary": entry.get("summary", ""),
        "raw_kind": entry.get("raw_kind", ""),
        "comment": entry.get("comment", ""),
        "signals": entry.get("signals", {}) or {},
        "also_covered_by": [],
        "cluster_size": 1,
    }


def merge_store(store, raw_items, now):
    """Merge freshly-collected raw items into the persisted store (keyed by
    item id), then roll off anything older than ROLLOFF_DAYS. Mutates and
    returns `store`."""
    now_iso = now.isoformat()
    normalized = score.normalize(raw_items)
    for item in normalized:
        existing = store.get(item["id"])
        if existing:
            item["first_seen"] = existing.get("first_seen")
        store[item["id"]] = _item_to_store_entry(item, now_iso)

    cutoff = now - timedelta(days=ROLLOFF_DAYS)
    to_delete = []
    for iid, entry in store.items():
        anchor = score._parse_dt(entry.get("published")) or score._parse_dt(entry.get("first_seen"))
        if anchor and anchor < cutoff:
            to_delete.append(iid)
    for iid in to_delete:
        del store[iid]

    return store


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    now = datetime.now(timezone.utc)
    all_sources = sources.all_sources()

    print(f"Collecting from {len(all_sources)} sources...")
    raw_items, health = collect.collect_all(all_sources)
    print(f"Fetched {len(raw_items)} raw items.\n")

    store = _load_store()
    before = len(store)
    store = merge_store(store, raw_items, now)
    after = len(store)
    _atomic_write_json(STORE_PATH, store)

    health_out = {name: dict(h) for name, h in health.items()}
    _atomic_write_json(HEALTH_PATH, health_out)

    items = [_store_entry_to_item(e) for e in store.values()]
    items = score.dedupe(items)
    for it in items:
        it["categories"] = score.classify(it)
        it["score_daily"] = score.score(it, now, use_recency=True)
        it["score_significance"] = score.score(it, now, use_recency=False)

    html = render.render(items, health_out, generated_at=now)
    _atomic_write_text(DASHBOARD_PATH, html)

    # --- per-source summary table -------------------------------------
    print(f"{'SOURCE':<42} {'OK':>4} {'COUNT':>6}  ERROR")
    print("-" * 100)
    for name in sorted(health.keys()):
        h = health[name]
        ok = "yes" if h["ok"] else "NO"
        err = (h["error"] or "")[:70]
        print(f"{name[:42]:<42} {ok:>4} {h['count']:>6}  {err}")

    failed = [n for n, h in health.items() if not h["ok"]]
    print()
    print(f"Sources OK: {len(health) - len(failed)}/{len(health)}" + (f"  FAILED: {', '.join(failed)}" if failed else ""))
    print(f"Store: {before} items -> {after} items after merge (rolled off items older than {ROLLOFF_DAYS} days)")
    print(f"Rendered {DASHBOARD_PATH} with {len(items)} deduped/scored items")


if __name__ == "__main__":
    main()
