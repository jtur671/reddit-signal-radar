"""Wikimedia pageviews — attention from outside the forums.

The board measures Reddit. This measures whether the wider world is looking a name up,
which is the discriminator between a real story and a brigade: a brigade moves Reddit
mentions without moving Wikipedia, a genuine story moves both.

Scored as a SELF-relative spike (today vs the ticker's own trailing median), not a
board-relative percentile -- a cross-sectional rank would mostly measure market cap, and
NVDA would outrank a genuinely spiking micro-cap every day.

Titles come from radar/tickermap.py and are EXACT. An unmapped ticker gets no request:
pageviews for a wrong article are a plausible, well-formed, entirely fictitious signal.
"""
from __future__ import annotations

import math
import statistics
import time
import urllib.parse
from datetime import date, timedelta

import requests

from radar import degrade

REST = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
        "en.wikipedia/all-access/user/{title}/daily/{start}/{end}")
UA = "reddit-signal-radar/0.1 (open-source ticker signal bot)"

BASELINE_DAYS = 28
FETCH_DAYS = 35          # slack, so missing datapoints still leave a full baseline


def spike_score(series, min_baseline: int = 10, min_days: int = 21) -> float | None:
    """0-100 from today's views against this ticker's own median. None when the signal
    would be noise: too few baseline days, or a baseline too thin to be meaningful."""
    if not series or len(series) < 2:
        return None
    current, prior = series[-1], series[-(BASELINE_DAYS + 1):-1]
    if len(prior) < min_days:
        return None
    baseline = statistics.median(prior)
    if baseline < min_baseline or current <= 0:
        return None
    ratio = current / baseline
    return round(50.0 + 25.0 * max(-2.0, min(2.0, math.log2(ratio))), 2)


def parse_series(raw) -> list[int]:
    """Chronological daily views. Pure, never raises."""
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            out.append(int(it["views"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _get_series(title: str, start: str, end: str) -> list[int] | None:
    """One request returns the whole window (measured: 34 datapoints in 0.22s)."""
    url = REST.format(title=urllib.parse.quote(title.replace(" ", "_"), safe=""),
                      start=start, end=end)
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
        if r.status_code != 200:
            return None
        return parse_series(r.json())
    except (requests.RequestException, ValueError):
        return None


def fetch_attention(titles: dict, tickers: list, run_day: str, sleep_s: float = 0.2):
    """({ticker: 0-100}, {ticker: latest views}) for mapped tickers. Fail-soft: a
    ticker that errors or scores None is simply absent from the scores dict."""
    end = date.fromisoformat(run_day) - timedelta(days=1)
    start = end - timedelta(days=FETCH_DAYS)
    s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    scores, raw_views, failures = {}, {}, 0
    for ticker in tickers:
        title = titles.get(ticker)
        if not title:
            continue
        series = _get_series(title, s, e)
        if not series:
            failures += 1
            continue
        raw_views[ticker] = series[-1]
        score = spike_score(series)
        if score is not None:
            scores[ticker] = score
        time.sleep(sleep_s)
    if failures:
        degrade.warn("wikimedia", f"{failures} ticker(s) returned no series")
    return scores, raw_views
