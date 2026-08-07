"""Tradestie WSB sentiment — free, keyless directional (Bullish/Bearish) per-ticker
sentiment for the top-50 r/wallstreetbets names (tradestie.com, 15-min refresh,
20 req/min limit; we make one call per day).

Two jobs: (1) annotate history.json with ts_bull/ts_comments so directional-sentiment
history accrues from today; (2) serve as a partial-board fallback when ApeWisdom is
down (top-50 WSB only). sentiment_score is a VADER-style compound in [-1, 1] per the
recorded fixture; bull_pct maps it to 0-100.

Endpoint note (2026-08-07): the old api.tradestie.com/v1/apps/reddit subdomain is dead
in production (TLS cert expired 2026-01-03; the origin returns HTTP 502 Bad Gateway
even with cert verification disabled) and has been unreliable since at least late 2025.
The live endpoint is on the apex domain instead: tradestie.com/api/v1/apps/reddit,
verified live (HTTP 200, real JSON, same documented shape) and used for DEFAULT_URL and
tests/fixtures/tradestie.json below; see task-2-report.md for the full verification
trail, including the earlier (now superseded) dead-subdomain diagnosis."""
from __future__ import annotations

import time
from dataclasses import dataclass

import requests

from radar import degrade
from radar.apewisdom import Aggregate

DEFAULT_URL = "https://tradestie.com/api/v1/apps/reddit"


@dataclass
class TsRow:
    ticker: str
    sentiment: str      # "Bullish" | "Bearish"
    score: float        # compound score, -1..1
    comments: int


def parse_feed(raw) -> list[TsRow]:
    """Pure, resilient parser. Never raises."""
    out: list[TsRow] = []
    if not isinstance(raw, list):
        return out
    for r in raw:
        if not isinstance(r, dict):
            continue
        tok = str(r.get("ticker") or "").upper().strip()
        if not tok:
            continue
        try:
            score = float(r.get("sentiment_score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        try:
            comments = max(0, int(r.get("no_of_comments") or 0))
        except (TypeError, ValueError):
            comments = 0
        out.append(TsRow(ticker=tok, sentiment=str(r.get("sentiment") or ""),
                         score=score, comments=comments))
    return out


def bull_pct(score: float) -> float:
    """Compound score -1..1 -> bullish share 0..100, clamped."""
    return round(50.0 * (1.0 + max(-1.0, min(1.0, score))), 1)


def _get(url: str, ua: str, retries: int, sleep_s: float):
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


def fetch_wsb(cfg) -> list[TsRow]:
    """One daily pull of the WSB top-50. Fail-soft: [] + degrade.warn on any failure."""
    ts = getattr(cfg, "tradestie", None)
    url = getattr(ts, "url", DEFAULT_URL)
    ua = getattr(ts, "user_agent", "reddit-signal-radar/0.1 (open-source ticker signal bot)")
    retries = int(getattr(ts, "max_retries", 3))
    sleep_s = float(getattr(ts, "sleep_seconds", 1.0))
    raw = _get(url, ua, retries, sleep_s)
    rows = parse_feed(raw)
    if not rows:
        degrade.warn("tradestie sentiment", "fetch returned nothing")
    return rows


def to_aggregates(rows: list[TsRow]) -> list[Aggregate]:
    """Fallback board input when ApeWisdom is empty: comment counts stand in for
    mentions (same attention semantics, narrower universe)."""
    return [Aggregate(ticker=r.ticker, name="", mentions=r.comments,
                      mentions_24h_ago=0, upvotes=0, subreddit="wallstreetbets")
            for r in rows if r.comments > 0]
