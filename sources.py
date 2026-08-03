"""
Source registry for the Daily Tech News Dashboard.

Each entry is a dict:
    {
        "name": str,           # human readable, unique-ish
        "url": str,            # endpoint / feed URL
        "kind": str,           # one of: rss, arxiv, hf_papers, hn
        "tier": float,         # 1.0 primary lab/research, 0.7 quality press, 0.4 aggregator
        "categories": list[str],  # hint categories; final classification is still done in score.py
    }

Tiering:
    1.0 -> primary lab/research blogs + arXiv + HF daily papers
    0.7 -> quality press / analysis
    0.4 -> aggregator volume (HN, MarkTechPost)
"""

# ---------------------------------------------------------------------------
# RSS / Atom sources
# ---------------------------------------------------------------------------

RSS_SOURCES = [
    # Tier 1.0 -- primary lab / research blogs
    {"name": "OpenAI Blog", "url": "https://openai.com/blog/rss.xml", "kind": "rss", "tier": 1.0, "categories": ["innovation"]},
    {"name": "DeepMind Blog", "url": "https://deepmind.google/blog/rss.xml", "kind": "rss", "tier": 1.0, "categories": ["innovation", "papers"]},
    {"name": "Google Research Blog", "url": "https://research.google/blog/rss/", "kind": "rss", "tier": 1.0, "categories": ["innovation", "papers"]},
    {"name": "Google AI Blog", "url": "https://blog.google/technology/ai/rss/", "kind": "rss", "tier": 1.0, "categories": ["innovation"]},
    {"name": "Microsoft Research", "url": "https://www.microsoft.com/en-us/research/feed/", "kind": "rss", "tier": 1.0, "categories": ["innovation", "papers"]},
    {"name": "NVIDIA Blog", "url": "https://blogs.nvidia.com/feed/", "kind": "rss", "tier": 1.0, "categories": ["innovation"]},
    {"name": "Apple Machine Learning Research", "url": "https://machinelearning.apple.com/rss.xml", "kind": "rss", "tier": 1.0, "categories": ["innovation", "papers"]},
    {"name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml", "kind": "rss", "tier": 1.0, "categories": ["innovation"]},

    # Tier 0.7 -- quality press / analysis
    {"name": "Ars Technica", "url": "https://arstechnica.com/feed/", "kind": "rss", "tier": 0.7, "categories": ["innovation"]},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml", "kind": "rss", "tier": 0.7, "categories": ["innovation"]},
    {"name": "IEEE Spectrum AI", "url": "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss", "kind": "rss", "tier": 0.7, "categories": ["innovation"]},
    {"name": "MIT Technology Review AI", "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed", "kind": "rss", "tier": 0.7, "categories": ["innovation"]},
    {"name": "Wired AI", "url": "https://www.wired.com/feed/tag/ai/latest/rss", "kind": "rss", "tier": 0.7, "categories": ["innovation"]},
    {"name": "VentureBeat AI", "url": "https://venturebeat.com/category/ai/feed/", "kind": "rss", "tier": 0.7, "categories": ["innovation"]},
    {"name": "Simon Willison", "url": "https://simonwillison.net/atom/everything/", "kind": "rss", "tier": 0.7, "categories": ["innovation", "agentic"]},
    {"name": "Import AI", "url": "https://importai.substack.com/feed", "kind": "rss", "tier": 0.7, "categories": ["innovation"]},
    {"name": "Anthropic (via Google News)", "url": "https://news.google.com/rss/search?q=Anthropic&hl=en-US&gl=US&ceid=US:en", "kind": "rss", "tier": 0.7, "categories": ["innovation"]},

    # Tier 0.4 -- aggregator volume
    {"name": "MarkTechPost", "url": "https://www.marktechpost.com/feed/", "kind": "rss", "tier": 0.4, "categories": ["innovation"]},
]

# ---------------------------------------------------------------------------
# arXiv sources
# ---------------------------------------------------------------------------

import urllib.parse

_ARXIV_BASE = "https://export.arxiv.org/api/query"


def _arxiv_url(search_query, max_results=50):
    qs = urllib.parse.urlencode({
        "search_query": search_query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results,
    })
    return f"{_ARXIV_BASE}?{qs}"


# Recent-papers firehose across the core categories.
_ARXIV_RECENT = {
    "name": "arXiv recent (cs.AI/CL/LG/MA)",
    "url": _arxiv_url("cat:cs.AI OR cat:cs.CL OR cat:cs.LG OR cat:cs.MA", max_results=75),
    "kind": "arxiv",
    "tier": 1.0,
    "categories": ["papers"],
}

# Accepted-paper queries per venue. arXiv comment field search (co:) hits the
# <arxiv:comment> tag; most hits are "under review"/"submitted to" so collect.py
# is responsible for filtering to accepted/oral/spotlight/camera-ready language.
_VENUES = [
    "NeurIPS", "ICML", "ICLR", "ACL", "EMNLP", "NAACL", "CVPR", "ICCV",
    "ECCV", "AAAI", "COLM", "KDD", "SIGGRAPH", "CoRL", "ICRA",
]
_VENUE_YEARS = ["2025", "2026"]

ARXIV_SOURCES = [_ARXIV_RECENT]
for venue in _VENUES:
    for year in _VENUE_YEARS:
        ARXIV_SOURCES.append({
            "name": f"arXiv accepted @ {venue} {year}",
            "url": _arxiv_url(f'co:"{venue} {year}"', max_results=50),
            "kind": "arxiv",
            "tier": 1.0,
            "categories": ["papers"],
            "venue": venue,
        })

# ---------------------------------------------------------------------------
# Hugging Face daily papers
# ---------------------------------------------------------------------------

HF_SOURCES = [
    {
        "name": "Hugging Face Daily Papers",
        "url": "https://huggingface.co/api/daily_papers",
        "kind": "hf_papers",
        "tier": 1.0,
        "categories": ["papers"],
        # collect.py walks backward day-by-day over this many days to backfill
        "backfill_days": 100,
    },
]

# ---------------------------------------------------------------------------
# Hacker News (Algolia) sources
# ---------------------------------------------------------------------------

_HN_BASE = "https://hn.algolia.com/api/v1/search_by_date"

_HN_QUERIES = ["AI", "agent", "agentic", "LLM", "machine learning"]

HN_SOURCES = [
    {
        "name": f"HN search: {q}",
        "url": f"{_HN_BASE}?tags=story&query={q.replace(' ', '+')}&numericFilters=points%3E75",
        "kind": "hn",
        "tier": 0.4,
        "categories": ["innovation", "agentic"],
    }
    for q in _HN_QUERIES
]

# ---------------------------------------------------------------------------
# Combined registry
# ---------------------------------------------------------------------------

SOURCES = RSS_SOURCES + ARXIV_SOURCES + HF_SOURCES + HN_SOURCES


def all_sources():
    return SOURCES
