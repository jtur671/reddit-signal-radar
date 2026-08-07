"""Company descriptions for the detail modal — 'what is HPE and why should I care'.

yfinance/.info is 429-blocked from cloud IPs, so we use Wikipedia's free, no-auth REST
summary API, keyed off the company name ApeWisdom already gives us. Results are cached
per-ticker in data/about.json (committed back), so each ticker is looked up once ever
and the dashboard is resilient to Wikipedia hiccups.
"""
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

import requests

from radar.degrade import warn

REST ="https://en.wikipedia.org/api/rest_v1/page/summary/"


def fetch_summary(name: str, ua: str = "reddit-signal-radar/0.1") -> dict | None:
    """Wikipedia one-line description + extract for a company name. Never raises."""
    if not name:
        return None
    title = urllib.parse.quote(name.replace(" ", "_"), safe="")
    try:
        r = requests.get(REST + title, headers={"User-Agent": ua}, timeout=15)
        if r.status_code != 200:
            warn(f"wikipedia {name}", f"HTTP {r.status_code}")
            return None
        d = r.json()
    except Exception as e:
        warn(f"wikipedia {name}", e)
        return None
    if d.get("type") == "disambiguation":
        return None
    return {"desc": (d.get("description") or "").strip(),
            "extract": (d.get("extract") or "").strip()}


def load_cache(path) -> dict:
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_cache(path, cache: dict) -> None:
    Path(path).write_text(json.dumps(cache, sort_keys=True))


def describe(ticker: str, name: str, cache: dict, ua: str = "reddit-signal-radar/0.1") -> dict:
    """Return {name, desc, extract} for a ticker, using the cache or a Wikipedia lookup.
    Always returns at least the company name; desc/extract are '' if unavailable.
    Mutates `cache` so the caller can persist newly-fetched entries."""
    cached = cache.get(ticker)
    if cached is not None:
        return cached
    summary = fetch_summary(name, ua) or {}
    entry = {"name": name or ticker, "desc": summary.get("desc", ""),
             "extract": summary.get("extract", "")}
    cache[ticker] = entry
    return entry
