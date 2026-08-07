"""Inverse-Cramer feed — Mad Money stock calls as a contrarian data point.

Source: the community `analyzing-stock-calls` dataset (nightly LLM transcriptions of
every Mad Money episode, keyless via raw.githubusercontent.com). It is a hobby repo
that could vanish, so every successful fetch is VENDORED to a data-branch snapshot and
the snapshot is the fallback when upstream disappears. This module only reports the
latest sentiment enum per ticker; the composite decides what 'inverse' means."""
from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path

import requests

from radar import degrade

DEFAULT_URL = ("https://raw.githubusercontent.com/jf-silverman/analyzing-stock-calls/"
               "main/data/stock_sentiments.json")


def _get_json(url: str, ua: str, retries: int = 2, sleep_s: float = 1.0):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers={"User-Agent": ua}, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503):
                time.sleep(sleep_s * (2 ** attempt)); continue
            return None
        except (requests.RequestException, ValueError):
            time.sleep(sleep_s * (2 ** attempt))
    return None


def parse_sentiments(raw, today: str, max_age_days: int) -> dict[str, str]:
    """{ticker: most-recent sentiment within the window}. Pure, never raises."""
    out: dict[str, str] = {}
    stocks = raw.get("stocks") if isinstance(raw, dict) else None
    if not isinstance(stocks, dict):
        return out
    cutoff = (date.fromisoformat(today) - timedelta(days=max_age_days)).isoformat()
    for tick, entry in stocks.items():
        mentions = entry.get("mentions") if isinstance(entry, dict) else None
        best_date, best_sent = "", ""
        for m in mentions or []:
            if not isinstance(m, dict):
                continue
            d, s = str(m.get("date") or ""), str(m.get("sentiment") or "")
            if d and s and d >= cutoff and d >= best_date:
                best_date, best_sent = d, s
        if best_sent:
            out[str(tick).upper()] = best_sent
    return out


def fetch_cramer(cfg, run_day: str) -> dict[str, str]:
    """Live fetch -> vendor snapshot -> parse; snapshot fallback on outage; {} + warn
    when both are gone. The snapshot rides the data branch (daily.yml cp line)."""
    cc = getattr(cfg, "cramer", None)
    url = getattr(cc, "url", DEFAULT_URL)
    max_age = int(getattr(cc, "max_age_days", 30))
    snap = Path(getattr(cc, "snapshot_path", "data/cramer_snapshot.json"))
    ua = "reddit-signal-radar/0.1 (open-source ticker signal bot)"
    raw = _get_json(url, ua)
    if raw is not None and isinstance(raw, dict) and raw.get("stocks"):
        try:
            text = json.dumps(raw, sort_keys=True)
            if not snap.exists() or snap.read_text() != text:
                snap.write_text(text)
        except OSError as e:
            degrade.warn("cramer snapshot write", e)
        return parse_sentiments(raw, run_day, max_age)
    try:
        cached = json.loads(snap.read_text())
        degrade.warn("cramer feed", "upstream unavailable — using vendored snapshot")
        return parse_sentiments(cached, run_day, max_age)
    except (OSError, ValueError):
        degrade.warn("cramer feed", "upstream and snapshot both unavailable")
        return {}
