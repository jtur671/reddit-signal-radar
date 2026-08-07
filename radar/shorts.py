"""FINRA daily short-sale volume — a free, keyless short-pressure signal.

Reg SHO daily files (cdn.finra.org, one pipe-delimited file per trading day, ~500KB,
FRACTIONAL share volumes) give per-symbol ShortVolume/TotalVolume. The ratio is a daily
bearish-pressure / dark-pool proxy whose cadence matches the bot. Files exist only for
trading days, so the fetcher walks back from run_day-1 until it finds one."""
from __future__ import annotations

import time
from datetime import date, timedelta

import requests

from radar import degrade

URL_TEMPLATE = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{yyyymmdd}.txt"


def _get_text(url: str, ua: str, retries: int = 2, sleep_s: float = 1.0) -> str | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers={"User-Agent": ua}, timeout=20)
            if r.status_code == 200:
                return r.text
            if r.status_code in (429, 500, 502, 503):
                time.sleep(sleep_s * (2 ** attempt)); continue
            return None
        except requests.RequestException:
            time.sleep(sleep_s * (2 ** attempt))
    return None


def parse_shvol(text) -> dict[str, float]:
    """Pipe-delimited Reg SHO file -> {symbol: short_ratio}. Pure, never raises.
    Rows with unparsable or zero TotalVolume are dropped."""
    out: dict[str, float] = {}
    if not isinstance(text, str):
        return out
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) < 5 or parts[0] == "Date":
            continue
        sym = parts[1].strip().upper()
        try:
            short, total = float(parts[2]), float(parts[4])
        except ValueError:
            continue
        if not sym or total <= 0:
            continue
        out[sym] = max(0.0, min(1.0, short / total))
    return out


def fetch_short_ratios(cfg, run_day: str) -> tuple[dict[str, float], str]:
    """Latest available day's ratios, walking back from run_day-1 (weekends/holidays
    have no file). Fail-soft: ({}, "") + one warn after the walk is exhausted."""
    fc = getattr(cfg, "finra", None)
    lookback = int(getattr(fc, "max_lookback_days", 5))
    ua = "reddit-signal-radar/0.1 (open-source ticker signal bot)"
    d = date.fromisoformat(run_day)
    for back in range(1, lookback + 1):
        stamp = (d - timedelta(days=back)).strftime("%Y%m%d")
        text = _get_text(URL_TEMPLATE.format(yyyymmdd=stamp), ua)
        if text:
            ratios = parse_shvol(text)
            if ratios:
                return ratios, stamp
    degrade.warn("finra short volume", f"no file found in {lookback} days before {run_day}")
    return {}, ""
