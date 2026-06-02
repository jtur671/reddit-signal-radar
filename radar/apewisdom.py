"""ApeWisdom data source — Reddit ticker-mention aggregates via the free, no-auth
apewisdom.io API. Used in place of raw Reddit JSON, which 403s from cloud/CI IPs.

Returns per-ticker daily aggregates (mention counts + 24h-ago + upvotes) that feed
the same freshness engine the raw-mention path uses; the bot scores these daily
counts against its own 90-day EMA baseline.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import requests


@dataclass
class Aggregate:
    ticker: str
    name: str
    mentions: int
    mentions_24h_ago: int
    upvotes: int
    subreddit: str            # the ApeWisdom filter this row came from


def _as_int(v) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 0
    return n if n >= 0 else 0


def parse_feed(raw: dict, source: str) -> list[Aggregate]:
    """Pure, resilient parser of one ApeWisdom page. Never raises."""
    out: list[Aggregate] = []
    results = raw.get("results") if isinstance(raw, dict) else None
    if not isinstance(results, list):
        return out
    for r in results:
        if not isinstance(r, dict):
            continue
        tok = str(r.get("ticker") or "").upper().strip()
        if tok.endswith(".X"):                  # ApeWisdom crypto suffix (BTC.X) -> bare symbol
            tok = tok[:-2]
        if not tok:
            continue
        out.append(Aggregate(
            ticker=tok,
            name=str(r.get("name") or ""),
            mentions=_as_int(r.get("mentions")),
            mentions_24h_ago=_as_int(r.get("mentions_24h_ago")),
            upvotes=_as_int(r.get("upvotes")),
            subreddit=source,
        ))
    return out


def _get(url: str, ua: str, retries: int, sleep_s: float) -> dict | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers={"User-Agent": ua}, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503):
                time.sleep(sleep_s * (2 ** attempt)); continue
            return None
        except requests.RequestException:
            time.sleep(sleep_s * (2 ** attempt))
    return None


def fetch_mentions(cfg) -> list[Aggregate]:
    """Pull configured ApeWisdom filters across pages and merge per ticker. Never raises.
    A ticker appearing in multiple filters has its counts summed."""
    ua = getattr(cfg.apewisdom, "user_agent", "reddit-signal-radar/0.1 (open-source ticker signal bot)")
    filters = list(getattr(cfg.apewisdom, "filters", ["all-stocks", "all-crypto"]))
    max_pages = int(getattr(cfg.apewisdom, "max_pages", 2))
    retries = int(getattr(cfg.apewisdom, "max_retries", 3))
    sleep_s = float(getattr(cfg.apewisdom, "sleep_seconds", 1.0))
    merged: dict[str, Aggregate] = {}
    for filt in filters:
        for page in range(1, max_pages + 1):
            url = f"https://apewisdom.io/api/v1.0/filter/{filt}/page/{page}"
            raw = _get(url, ua, retries, sleep_s)
            time.sleep(sleep_s)
            if not raw:
                break                            # stop paging this filter on any failure
            rows = parse_feed(raw, source=filt)
            if not rows:
                break
            for a in rows:
                m = merged.get(a.ticker)
                if m is None:
                    merged[a.ticker] = a
                else:
                    m.mentions += a.mentions
                    m.upvotes += a.upvotes
                    m.mentions_24h_ago += a.mentions_24h_ago
    return list(merged.values())
