"""
Fetch + normalize layer for the Daily Tech News Dashboard.

fetch(source) -> list[dict] dispatches on source["kind"] to one of the
kind-specific fetchers below. Every item is normalized to at least:

    {title, url, published (ISO8601 string or None), summary,
     source_name, source_url, raw_kind, tier, categories, ...kind-specific}

collect_all(sources) drives the whole run: RSS + HN fetch in parallel via a
ThreadPoolExecutor, HF daily-papers backfill runs its own internal thread
pool per source, and arXiv queries run strictly serially with a ~3s delay
between requests (shared rate-limited API). Every source gets one retry on
failure; a failing source is recorded in the health dict and never raises
out of collect_all.
"""

import concurrent.futures
import datetime
import email.utils
import html
import json
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

USER_AGENT = "Mozilla/5.0 (compatible; TechNewsDashboard/1.0)"
TIMEOUT = 15

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

_ACCEPT_RE = re.compile(r"accepted|to appear|camera.?ready|oral|spotlight", re.I)
_REJECT_RE = re.compile(r"under review|submitted to", re.I)


# ---------------------------------------------------------------------------
# HTTP / parsing helpers
# ---------------------------------------------------------------------------

def _http_get(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_date(s):
    """Best-effort parse of RFC822 or ISO8601 into a UTC ISO8601 string."""
    if not s:
        return None
    s = s.strip()
    try:
        dt = email.utils.parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc).isoformat()
    except Exception:
        pass
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc).isoformat()
    except Exception:
        pass
    return None


def _base_item(source, raw_kind):
    return {
        "source_name": source["name"],
        "source_url": source["url"],
        "raw_kind": raw_kind,
        "tier": source.get("tier", 0.4),
        "categories": source.get("categories", []),
    }


# ---------------------------------------------------------------------------
# RSS / Atom
# ---------------------------------------------------------------------------

def fetch_rss(source):
    raw = _http_get(source["url"])
    root = ET.fromstring(raw)
    items = []

    channel_items = root.findall(".//item")
    if channel_items:
        for it in channel_items:
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            pub = it.findtext("pubDate") or ""
            desc = it.findtext("description") or it.findtext("summary") or ""
            item = _base_item(source, "rss")
            item.update({
                "title": html.unescape(title),
                "url": link,
                "published": _parse_date(pub),
                "summary": _strip_html(desc)[:600],
            })
            items.append(item)
        return items

    # Atom feed
    entries = root.findall(".//atom:entry", ATOM_NS)
    for e in entries:
        title = (e.findtext("atom:title", default="", namespaces=ATOM_NS) or "").strip()
        link = ""
        link_els = e.findall("atom:link", ATOM_NS)
        for le in link_els:
            rel = le.get("rel")
            if rel in (None, "alternate"):
                link = le.get("href") or ""
                break
        if not link and link_els:
            link = link_els[0].get("href") or ""
        if not link:
            link = (e.findtext("atom:id", default="", namespaces=ATOM_NS) or "").strip()
        pub = e.findtext("atom:published", default=None, namespaces=ATOM_NS)
        if not pub:
            pub = e.findtext("atom:updated", default="", namespaces=ATOM_NS)
        summary = e.findtext("atom:summary", default="", namespaces=ATOM_NS)
        if not summary:
            summary = e.findtext("atom:content", default="", namespaces=ATOM_NS) or ""
        item = _base_item(source, "rss")
        item.update({
            "title": html.unescape(re.sub(r"\s+", " ", title)),
            "url": link,
            "published": _parse_date(pub),
            "summary": _strip_html(summary)[:600],
        })
        items.append(item)
    return items


# ---------------------------------------------------------------------------
# arXiv
# ---------------------------------------------------------------------------

def fetch_arxiv(source):
    raw = _http_get(source["url"])
    root = ET.fromstring(raw)
    items = []
    venue = source.get("venue")

    for e in root.findall("atom:entry", ARXIV_NS):
        title = (e.findtext("atom:title", default="", namespaces=ARXIV_NS) or "").strip()
        title = re.sub(r"\s+", " ", title)
        url_ = (e.findtext("atom:id", default="", namespaces=ARXIV_NS) or "").strip()
        published = _parse_date(e.findtext("atom:published", default="", namespaces=ARXIV_NS))
        summary = _strip_html(e.findtext("atom:summary", default="", namespaces=ARXIV_NS) or "")[:600]
        comment = (e.findtext("arxiv:comment", default="", namespaces=ARXIV_NS) or "").strip()
        authors = [
            (a.findtext("atom:name", default="", namespaces=ARXIV_NS) or "").strip()
            for a in e.findall("atom:author", ARXIV_NS)
        ]

        if venue:
            # Venue-specific accepted-paper query: only keep genuinely accepted
            # hits, filtering out "under review at / submitted to X" noise.
            if _REJECT_RE.search(comment) or not _ACCEPT_RE.search(comment):
                continue

        item = _base_item(source, "arxiv")
        item.update({
            "title": html.unescape(title),
            "url": url_,
            "published": published,
            "summary": summary,
            "authors": authors,
            "comment": comment,
        })
        if venue:
            item["venue"] = venue
        items.append(item)
    return items


# ---------------------------------------------------------------------------
# Hugging Face daily papers
# ---------------------------------------------------------------------------

def _fetch_hf_day(date_str, source):
    url = f"{source['url']}?date={date_str}"
    raw = _http_get(url)
    data = json.loads(raw)
    items = []
    if not isinstance(data, list):
        return items
    for entry in data:
        paper = entry.get("paper") or {}
        pid = paper.get("id")
        if not pid:
            continue
        title = (paper.get("title") or entry.get("title") or "").strip()
        published = paper.get("publishedAt") or entry.get("publishedAt")
        authors = []
        for a in paper.get("authors", []) or []:
            if isinstance(a, dict) and a.get("name"):
                authors.append(a["name"])
        item = _base_item(source, "hf_papers")
        item.update({
            "title": title,
            "url": f"https://huggingface.co/papers/{pid}",
            "published": _parse_date(published),
            "summary": _strip_html(paper.get("summary") or "")[:600],
            "hf_upvotes": paper.get("upvotes", 0) or 0,
            "authors": authors,
            "github_repo": paper.get("githubRepo"),
        })
        items.append(item)
    return items


def fetch_hf_papers(source):
    days = source.get("backfill_days", 100)
    today = datetime.date.today()
    dates = [(today - datetime.timedelta(days=i)).isoformat() for i in range(days)]
    items = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_fetch_hf_day, d, source): d for d in dates}
        for fut in concurrent.futures.as_completed(futures):
            try:
                items.extend(fut.result())
            except Exception:
                # Individual day failures (including legitimately empty days)
                # are tolerated -- the overall source is still healthy.
                continue
    return items


# ---------------------------------------------------------------------------
# Hacker News (Algolia)
# ---------------------------------------------------------------------------

def fetch_hn(source):
    raw = _http_get(source["url"])
    data = json.loads(raw)
    items = []
    for hit in data.get("hits", []):
        obj_id = hit.get("objectID")
        url_ = hit.get("url") or (f"https://news.ycombinator.com/item?id={obj_id}" if obj_id else None)
        if not url_:
            continue
        item = _base_item(source, "hn")
        item.update({
            "title": (hit.get("title") or "").strip(),
            "url": url_,
            "published": _parse_date(hit.get("created_at")),
            "summary": "",
            "hn_points": hit.get("points", 0) or 0,
            "hn_comments": hit.get("num_comments", 0) or 0,
        })
        items.append(item)
    return items


# ---------------------------------------------------------------------------
# Dispatch + orchestration
# ---------------------------------------------------------------------------

def fetch(source):
    kind = source["kind"]
    if kind == "rss":
        return fetch_rss(source)
    if kind == "arxiv":
        return fetch_arxiv(source)
    if kind == "hf_papers":
        return fetch_hf_papers(source)
    if kind == "hn":
        return fetch_hn(source)
    raise ValueError(f"unknown source kind: {kind!r}")


def _fetch_with_retry(source, retries=1):
    last_err = None
    for attempt in range(retries + 1):
        try:
            return fetch(source), None
        except Exception as e:  # noqa: BLE001 -- a source must never crash the run
            last_err = e
    return [], last_err


def collect_all(sources):
    """Run the full collection pass. Returns (items, health)."""
    health = {}
    all_items = []

    rss_sources = [s for s in sources if s["kind"] == "rss"]
    hn_sources = [s for s in sources if s["kind"] == "hn"]
    hf_sources = [s for s in sources if s["kind"] == "hf_papers"]
    arxiv_sources = [s for s in sources if s["kind"] == "arxiv"]

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # RSS + HN: independent, quick HTTP calls -- fine to parallelize.
    parallel_sources = rss_sources + hn_sources
    if parallel_sources:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            futures = {ex.submit(_fetch_with_retry, s): s for s in parallel_sources}
            for fut in concurrent.futures.as_completed(futures):
                s = futures[fut]
                items, err = fut.result()
                all_items.extend(items)
                health[s["name"]] = {
                    "ok": err is None,
                    "count": len(items),
                    "error": str(err) if err else None,
                    "last_run": now,
                }

    # HF daily papers: each source internally parallelizes its day-walk.
    for s in hf_sources:
        items, err = _fetch_with_retry(s)
        all_items.extend(items)
        health[s["name"]] = {
            "ok": err is None,
            "count": len(items),
            "error": str(err) if err else None,
            "last_run": now,
        }

    # arXiv: serial with a delay between calls to respect the shared API.
    for i, s in enumerate(arxiv_sources):
        items, err = _fetch_with_retry(s)
        all_items.extend(items)
        health[s["name"]] = {
            "ok": err is None,
            "count": len(items),
            "error": str(err) if err else None,
            "last_run": now,
        }
        if i < len(arxiv_sources) - 1:
            time.sleep(3)

    return all_items, health
