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


def _mapped_title(entry: dict) -> str:
    """The MAPPED title an entry was built from — the only thing a fresh map may be
    compared against.

    The two titles in play are different KINDS and must never be compared to each other.
    `entry["title"]` is CANONICAL (post-redirect, read off the REST summary response);
    the incoming argument is MAPPED (from tickermap, whose Wikidata sitelinks include
    redirect titles). For any redirect-mapped ticker the two legitimately differ on every
    run — `Dow Inc.` in, `Dow Chemical Company` cached — so `entry["title"] != title`
    would re-fetch that ticker forever: one extra live request per redirect ticker per
    day, inside the job that gates the 6:17 AM publish. Stamping the mapped title into
    the entry is what makes "did the mapping change?" answerable at all.

    Entries written before the stamp existed fall back to the canonical title. That is
    exact for the common case (mapped == canonical, so an unchanged map stays a hit) and
    costs at most ONE healing fetch for a redirect-mapped ticker, after which the entry
    carries its stamp and is stable. Chosen over bumping SCHEMA, which would have been
    the house pattern but throws the entire live cache away to answer one question."""
    return entry.get("mapped", entry.get("title", ""))


def describe(ticker: str, name: str, title: str | None, cache: dict,
             ua: str = "reddit-signal-radar/0.1") -> dict:
    """Return {name, desc, extract, title, mapped} for a ticker. `title` is the exact
    Wikipedia article title from the ticker map, or None when the ticker is unmapped —
    in which case NO request is made. The cached `title` is the CANONICAL one off the
    response, not the one we asked for, so a redirect title in the map doesn't
    propagate; `mapped` records what we DID ask for. Mutates `cache` so the caller can
    persist new entries.

    A cached entry is a permanent hit only while BOTH hold: it already carries a title,
    and the mapping that produced it is unchanged. Everything else re-fetches, because
    the two inputs both move:

      - The map GROWS. An unmapped ticker caches as blank, and treating that as a hit
        forever would render every curated entry in radar/ticker_overrides.yml inert for
        any ticker that reached the board before its override existed — along with the
        monthly Wikidata refresh and the canonical title the pageviews ingest reads.
      - The map is CORRECTED. ticker_overrides.yml exists to be edited, and the Wikidata
        snapshot refreshes monthly, so a resolved entry can become the wrong entity by a
        change upstream of it. Keying the hit on the mapped title (see _mapped_title, and
        note it is NOT the cached title) is what lets that correction land. This matters
        beyond the blurb: run.py prefers the cached title when it asks Wikimedia for
        pageviews, and a stale title can itself be a redirect — measured 12 views/day
        against the canonical article's 468.

    A blank entry with still no title makes no request, so none of this is a daily retry
    of nothing."""
    cached = cache.get(ticker)
    if cached is not None and (not title
                               or (cached.get("title") and _mapped_title(cached) == title)):
        return cached
    summary = (fetch_summary(title, ua) or {}) if title else {}
    entry = {"name": name or ticker, "desc": summary.get("desc", ""),
             "extract": summary.get("extract", ""), "title": summary.get("title", ""),
             "mapped": title or ""}
    cache[ticker] = entry
    return entry
