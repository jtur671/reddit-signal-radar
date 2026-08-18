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

from radar import atomic
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
        # Inside the try, and type-guarded, both on purpose. "Never raises" has to hold
        # against what ARRIVES, not against what the REST docs promise: a 200 carrying
        # `null`, `[]`, `"..."` or `5` (a proxy error page, a cached empty response) hit
        # `d.get` and threw AttributeError from OUTSIDE the try, straight up through
        # describe() -> _enrich_ticker() -> main(). The run died before rendering — no
        # board, no publish — because one ticker got a malformed body.
        if not isinstance(d, dict) or d.get("type") == "disambiguation":
            return None
        # str() rather than trusting the field types: `(d.get("title") or "").strip()`
        # is an AttributeError on a numeric field, and a non-string `title` that reached
        # the cache is what run.py hands to pageviews.fetch_attention — this module's
        # bad data detonating in a different module.
        return {"desc": str(d.get("description") or "").strip(),
                "extract": str(d.get("extract") or "").strip(),
                "title": str(d.get("title") or "").strip()}
    except Exception as e:
        warn(f"wikipedia {title}", e)
        return None


# Paths whose last load was a CORRUPT read, keyed by path string. See load_cache for
# why the distinction exists and save_cache for what it does about it. Module state
# rather than a flag on the returned dict, deliberately: what needs protecting is the
# FILE, and run.py mutates and re-saves the dict load_cache handed it, so a caller that
# builds its own dict (or an entirely separate code path) would silently lose the veto.
# Keyed on the path as spelled, which is how both calls in run.py spell it.
_CORRUPT_READS: set[str] = set()


def _key(path) -> str:
    return str(Path(path))


def _corrupt(path, reason: object) -> dict:
    """Record that this path holds something we could not read, and warn."""
    _CORRUPT_READS.add(_key(path))
    warn("about cache read", reason)
    return {}


def load_cache(path) -> dict:
    """Entries for the current schema only. A cache written by an older schema is
    discarded wholesale: the pre-SCHEMA-1 file holds wrong-entity entries that are
    cache HITS, so they would never re-fetch and never heal.

    Returning {} on any failure was silent data loss, not a degraded read. run.py
    enriches only the ~15-30 tickers on TODAY's board into whatever dict this returns
    and then saves — so a failed read of a 3,000-entry cache does not degrade the run,
    it REPLACES the accumulated cache with today's board and commits that to the data
    branch. So the two cases are distinguished:

      EMPTY   — no file, or a zero-length one. Genuinely nothing to lose, and the state
                every first run starts in; refusing to write here would mean the cache
                could never be created at all.
      CORRUPT — the file exists and holds bytes, but they will not parse into a cache.
                That is damage (a hand-edit on the data branch, a bad blob, a non-UTF-8
                byte, a partial write from before atomic.write_text landed), and the
                entries are still sitting in the file. The read degrades to {} so the
                run continues, but the path is recorded and save_cache then REFUSES to
                overwrite it.

    A stale/absent SCHEMA is neither: discarding it is the deliberate, tested migration,
    so that path returns {} AND clears the veto so the rewrite lands."""
    try:
        raw = Path(path).read_text()
    except FileNotFoundError:
        _CORRUPT_READS.discard(_key(path))
        return {}
    except (OSError, ValueError) as e:
        # Exists (or is a directory, or is unreadable) — cannot prove it is empty, and
        # os.replace only needs the PARENT to be writable, so a write could still clobber it.
        # ValueError is NOT decoration: `read_text()` on a file carrying a non-UTF-8 byte
        # raises UnicodeDecodeError, which is a ValueError and not an OSError, so it
        # escaped this clause, escaped main(), and killed the run before anything was
        # written. This file rides the orphan data branch and daily.yml restores it before
        # EVERY run, so one bad byte crashed the publish every morning until a human
        # hand-edited the branch. Same defect, same call, already fixed in
        # short_interest._read_snapshot (9d5f3c6). It belongs on THIS side of the
        # empty/corrupt split: the file exists and holds bytes we could not read.
        return _corrupt(path, e)
    if not raw.strip():
        _CORRUPT_READS.discard(_key(path))
        return {}
    try:
        doc = json.loads(raw)
    except ValueError as e:
        return _corrupt(path, e)
    if not isinstance(doc, dict):
        return _corrupt(path, f"top level is {type(doc).__name__}, not an object")
    # `type(...) is int` rather than `!= SCHEMA`: True == 1 in Python, so `"schema": true`
    # passed the check and resurrected exactly the wrong-entity cache it exists to discard.
    if type(doc.get("schema")) is not int or doc.get("schema") != SCHEMA:
        _CORRUPT_READS.discard(_key(path))      # the deliberate discard, not damage
        return {}
    entries = doc.get("entries")
    if not isinstance(entries, dict):
        return _corrupt(path, f"entries is {type(entries).__name__}, not an object")
    _CORRUPT_READS.discard(_key(path))
    # Every VALUE was passed through untouched, so `{"AAPL": 5}` on the data branch
    # reached describe() and `cached.get("title")` raised. One poisoned entry must cost
    # that entry, not the run and not the other 3,000.
    clean = {k: v for k, v in entries.items() if isinstance(v, dict)}
    if len(clean) != len(entries):
        warn("about cache read", f"dropped {len(entries) - len(clean)} non-object entries")
    return clean


def save_cache(path, cache: dict) -> None:
    """Persist the cache, fail-soft. run.py calls this unguarded AFTER every enrichment
    and BEFORE the render, so anything that escapes here throws away a completed run at
    the last step: an unwritable path, a full disk, a value json cannot encode, or a
    cache whose mixed-type keys cannot be sorted."""
    if _key(path) in _CORRUPT_READS:
        warn("about cache write", "refusing to overwrite a cache that failed to load")
        return
    try:
        atomic.write_text(path, json.dumps({"schema": SCHEMA, "entries": cache},
                                           sort_keys=True))
    except (OSError, TypeError, ValueError) as e:
        warn("about cache write", e)


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
    # isinstance rather than `is not None`: load_cache drops non-dict entries, but the
    # cache is a caller-supplied argument and the loader is not the only way one gets in.
    cached = cache.get(ticker)
    if isinstance(cached, dict) and (not title
                                     or (cached.get("title") and _mapped_title(cached) == title)):
        return cached
    summary = (fetch_summary(title, ua) or {}) if title else {}
    entry = {"name": name or ticker, "desc": summary.get("desc", ""),
             "extract": summary.get("extract", ""), "title": summary.get("title", ""),
             "mapped": title or ""}
    cache[ticker] = entry
    return entry
