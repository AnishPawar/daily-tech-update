"""
normalize() / dedupe() / classify() / score() for the Daily Tech News Dashboard.

Pipeline (see refresh.py for how these compose with the persistent store):

    items = normalize(raw_items)       # -> list[Item], Item.published is a datetime
    items = dedupe(items)               # -> clusters merged, also_covered_by populated
    for it in items:
        it["categories"] = classify(it)
        it["score_daily"] = score(it, now, use_recency=True)
        it["score_significance"] = score(it, now, use_recency=False)
"""

import hashlib
import math
import re
import urllib.parse
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# normalize()
# ---------------------------------------------------------------------------

def canonical_url(url):
    """Lowercase host, strip query params/fragment/trailing slash."""
    if not url:
        return ""
    parts = urllib.parse.urlsplit(url.strip())
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/")
    scheme = parts.scheme.lower() or "https"
    return urllib.parse.urlunsplit((scheme, netloc, path, "", ""))


def item_id(url):
    cu = canonical_url(url)
    return hashlib.sha256(cu.encode("utf-8")).hexdigest()[:16]


def _parse_dt(value):
    """Accept a datetime, an ISO string, or None -> tz-aware datetime or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            s = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def normalize(raw_items):
    """Normalize raw collect.py items into the common Item shape."""
    out = []
    seen_ids = set()
    for r in raw_items:
        url = (r.get("url") or "").strip()
        title = (r.get("title") or "").strip()
        if not url or not title:
            continue
        iid = item_id(url)
        if iid in seen_ids:
            # exact duplicate within this batch (e.g. same paper hit by two
            # arXiv queries) -- keep the first, skip the rest here; dedupe()
            # still handles cross-batch merges against the persistent store.
            continue
        seen_ids.add(iid)
        item = {
            "id": iid,
            "canonical_url": canonical_url(url),
            "title": title,
            "url": url,
            "source": r.get("source_name", "unknown"),
            "source_url": r.get("source_url", ""),
            "tier": float(r.get("tier", 0.4)),
            "published": _parse_dt(r.get("published")),
            "summary": r.get("summary", "") or "",
            "raw_kind": r.get("raw_kind", "rss"),
            "comment": r.get("comment", ""),
            "signals": {
                "hn_points": r.get("hn_points"),
                "hn_comments": r.get("hn_comments"),
                "hf_upvotes": r.get("hf_upvotes"),
                "venue": r.get("venue"),
            },
            "also_covered_by": [],
            "cluster_size": 1,
        }
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# dedupe()
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "for", "to", "and", "or", "with",
    "without", "from", "by", "at", "is", "are", "was", "were", "be", "been",
    "being", "this", "that", "these", "those", "as", "it", "its", "into",
    "over", "under", "new", "how", "why", "what", "your", "you", "we", "our",
    "vs", "via", "using", "use", "can", "will", "now", "up", "out", "about",
}


def _tokenize_title(title):
    t = re.sub(r"[^a-z0-9\s]", " ", title.lower())
    return {w for w in t.split() if len(w) > 2 and w not in _STOPWORDS}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


class _UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)


def dedupe(items):
    """
    Cluster items that cover the same story.

    Pass 1: exact canonical-URL match (covers the common case -- the same
    arXiv id or the same article URL surfacing from more than one source).

    Pass 2: title-similarity clustering (Jaccard >= 0.6 over stopword-
    stripped tokens), restricted to non-paper items -- research papers are
    already almost entirely deduped by pass 1 (same arXiv/HF id), and running
    O(n^2)-ish fuzzy matching over thousands of paper titles would be wasted
    work; press/HN coverage of the same story is exactly the case this pass
    is for.

    The highest-tier item in each cluster becomes the primary; the rest are
    recorded by source name in `also_covered_by`, and `cluster_size` is set
    on the primary (== 1 + len(also_covered_by)).
    """
    url_groups = {}
    for it in items:
        url_groups.setdefault(it["canonical_url"], []).append(it)

    clusters = []
    fuzzy_pool = []
    for group in url_groups.values():
        if len(group) > 1:
            clusters.append(group)
        else:
            fuzzy_pool.append(group[0])

    paper_kinds = {"arxiv", "hf_papers"}
    fuzzy_candidates = [it for it in fuzzy_pool if it["raw_kind"] not in paper_kinds]
    leftover_papers = [it for it in fuzzy_pool if it["raw_kind"] in paper_kinds]

    tokens_list = [_tokenize_title(it["title"]) for it in fuzzy_candidates]
    uf = _UnionFind(len(fuzzy_candidates))
    inverted = {}
    for idx, toks in enumerate(tokens_list):
        for t in toks:
            inverted.setdefault(t, []).append(idx)

    for idxs in inverted.values():
        # Skip overly common tokens -- they blow up pairwise comparisons
        # without adding clustering signal.
        if len(idxs) < 2 or len(idxs) > 60:
            continue
        for i in range(len(idxs)):
            for j in range(i + 1, len(idxs)):
                a, b = idxs[i], idxs[j]
                if uf.find(a) == uf.find(b):
                    continue
                if _jaccard(tokens_list[a], tokens_list[b]) >= 0.6:
                    uf.union(a, b)

    groups = {}
    for idx in range(len(fuzzy_candidates)):
        r = uf.find(idx)
        groups.setdefault(r, []).append(fuzzy_candidates[idx])
    clusters.extend(groups.values())

    for it in leftover_papers:
        clusters.append([it])

    result = []
    for cluster in clusters:
        cluster_sorted = sorted(
            cluster,
            key=lambda x: (-x["tier"], -(x["published"] or _EPOCH).timestamp()),
        )
        primary = dict(cluster_sorted[0])
        also = [c["source"] for c in cluster_sorted[1:]]
        primary["also_covered_by"] = also
        primary["cluster_size"] = len(cluster)
        result.append(primary)

    return result


# ---------------------------------------------------------------------------
# classify()
# ---------------------------------------------------------------------------

_AGENTIC_RE = re.compile(
    r"agent(ic)?s?\b|tool[- ]use|\bmcp\b|model context protocol|computer use|"
    r"multi-agent|orchestrat|autonomous|langgraph|autogen|crewai|\bharness(es)?\b|"
    r"rl environment|agent framework",
    re.IGNORECASE,
)

_PAPER_TEXT_RE = re.compile(r"\bpaper\b|\bstudy\b|\bresearch\b", re.IGNORECASE)

_PAPER_KINDS = {"arxiv", "hf_papers"}


def classify(item):
    """Multi-label category classification. Returns a sorted list of tags
    drawn from {"agentic", "papers", "innovation"}. "innovation" is only
    applied as a fallback when neither of the other two match."""
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    cats = set()

    if _AGENTIC_RE.search(text):
        cats.add("agentic")

    is_paper_kind = item.get("raw_kind") in _PAPER_KINDS
    has_arxiv_link = "arxiv.org" in (item.get("url") or "")
    if is_paper_kind or (has_arxiv_link and _PAPER_TEXT_RE.search(text)):
        cats.add("papers")

    if not cats:
        cats.add("innovation")

    return sorted(cats)


# ---------------------------------------------------------------------------
# score()
# ---------------------------------------------------------------------------

_HALF_LIFE_DAYS = 10.0


def recency_decay(published, now):
    if not published:
        return 0.0
    age_days = (now - published).total_seconds() / 86400.0
    if age_days < 0:
        age_days = 0.0
    return math.exp(-math.log(2) * age_days / _HALF_LIFE_DAYS)


def score(item, now, use_recency=True):
    tier = item.get("tier", 0.4)
    signals = item.get("signals", {}) or {}
    hn_points = signals.get("hn_points") or 0
    hf_upvotes = signals.get("hf_upvotes") or 0
    n_sources = item.get("cluster_size", 1)
    accepted_top_tier_venue = bool(signals.get("venue"))

    s = tier
    s += 0.8 * math.log1p(hn_points) / math.log1p(1000)
    s += 0.8 * math.log1p(hf_upvotes) / math.log1p(300)
    s += 0.5 * max(0, n_sources - 1)
    if accepted_top_tier_venue:
        s += 0.6
    if use_recency:
        s += recency_decay(item.get("published"), now)
    return s


# ---------------------------------------------------------------------------
# Convenience pipeline
# ---------------------------------------------------------------------------

def process(raw_items, now=None):
    """normalize -> dedupe -> classify -> score, in one call. Used directly
    by refresh.py against the merged persistent store."""
    if now is None:
        now = datetime.now(timezone.utc)
    items = normalize(raw_items)
    items = dedupe(items)
    for it in items:
        it["categories"] = classify(it)
        it["score_daily"] = score(it, now, use_recency=True)
        it["score_significance"] = score(it, now, use_recency=False)
    return items
