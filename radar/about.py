"""Company descriptions for the detail modal — 'what is HPE and why should I care'.

yfinance/.info is 429-blocked from cloud IPs, so we use Wikipedia's free, no-auth REST
summary API. The article title comes from radar/tickermap.py as an EXACT title; this
module never guesses one from a company name. It used to, and the result was AAPL ->
"Apple" -> "Edible fruit" on 13.7% of the board. A ticker with no mapping gets no
description — that is the correct outcome, not a gap to paper over.

Results are cached per-ticker in data/about.json (committed back), so each ticker is
looked up once ever and the dashboard is resilient to Wikipedia hiccups.
"""
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

import requests

from radar.degrade import warn

REST = "https://en.wikipedia.org/api/rest_v1/page/summary/"

SCHEMA = 1


def fetch_summary(title: str, ua: str = "reddit-signal-radar/0.1") -> dict | None:
    """Wikipedia one-line description + extract for an EXACT article title. Never raises.

    Also returns the response's own `title`, which is the CANONICAL one: this endpoint
    follows redirects (verified live — .../summary/Dow_Inc. answers with title
    "Dow Chemical Company"). The pageviews API does NOT follow redirects; it returns
    HTTP 200 with the redirect page's own traffic, measured at 12 views/day against the
    canonical article's 468 — a 39x silent understatement. Capturing the canonical title
    here hands that to the pageviews ingest for free, on a call we already make."""
    if not title:
        return None
    quoted = urllib.parse.quote(title.replace(" ", "_"), safe="")
    try:
        r = requests.get(REST + quoted, headers={"User-Agent": ua}, timeout=15)
        if r.status_code != 200:
            warn(f"wikipedia {title}", f"HTTP {r.status_code}")
            return None
        d = r.json()
    except Exception as e:
        warn(f"wikipedia {title}", e)
        return None
    if d.get("type") == "disambiguation":
        return None
    return {"desc": (d.get("description") or "").strip(),
            "extract": (d.get("extract") or "").strip(),
            "title": (d.get("title") or "").strip()}


def load_cache(path) -> dict:
    """Entries for the current schema only. A cache written by an older schema is
    discarded wholesale: the pre-SCHEMA-1 file holds wrong-entity entries that are
    cache HITS, so they would never re-fetch and never heal."""
    try:
        doc = json.loads(Path(path).read_text())
    except Exception:
        return {}
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        return {}
    entries = doc.get("entries")
    return entries if isinstance(entries, dict) else {}


def save_cache(path, cache: dict) -> None:
    Path(path).write_text(json.dumps({"schema": SCHEMA, "entries": cache}, sort_keys=True))


def describe(ticker: str, name: str, title: str | None, cache: dict,
             ua: str = "reddit-signal-radar/0.1") -> dict:
    """Return {name, desc, extract, title} for a ticker. `title` is the exact Wikipedia
    article title from the ticker map, or None when the ticker is unmapped — in which
    case NO request is made. The cached `title` is the CANONICAL one off the response,
    not the one we asked for, so a redirect title in the map doesn't propagate. Mutates
    `cache` so the caller can persist new entries."""
    cached = cache.get(ticker)
    if cached is not None:
        return cached
    summary = (fetch_summary(title, ua) or {}) if title else {}
    entry = {"name": name or ticker, "desc": summary.get("desc", ""),
             "extract": summary.get("extract", ""), "title": summary.get("title", "")}
    cache[ticker] = entry
    return entry
