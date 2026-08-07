"""CBOE delayed options chains — a free, keyless unusual-options-activity-lite signal.

cdn.cboe.com serves the full delayed chain (~1.6MB/symbol) with per-contract volume,
open interest, and IV. We compute a put/call volume ratio and a coarse UOA flag
(day volume unusually large vs. resting open interest) for the TOP BOARD MOVERS ONLY
— the payload size makes an all-board sweep rude and slow."""
from __future__ import annotations

import re
import time

import requests

from radar import degrade

CHAIN_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"
_OCC = re.compile(r"^[A-Z0-9.]{1,6}\d{6}([CP])\d{8}$")


def is_put(symbol) -> bool | None:
    """OCC-style symbol -> put? (None when unclassifiable)."""
    m = _OCC.match(str(symbol or ""))
    return None if not m else m.group(1) == "P"


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


def parse_chain(raw) -> dict:
    """Chain JSON -> volume/OI aggregates. Pure, never raises."""
    call_vol = put_vol = total_vol = total_oi = 0.0
    try:
        options = raw["data"]["options"]
    except (TypeError, KeyError):
        options = []
    for o in options or []:
        if not isinstance(o, dict):
            continue
        try:
            vol = float(o.get("volume") or 0)
            oi = float(o.get("open_interest") or 0)
        except (TypeError, ValueError):
            continue
        total_vol += vol
        total_oi += oi
        side = is_put(o.get("option"))
        if side is True:
            put_vol += vol
        elif side is False:
            call_vol += vol
    return {"pc_ratio": (put_vol / call_vol if call_vol > 0 else None),
            "call_vol": call_vol, "put_vol": put_vol,
            "total_vol": total_vol, "total_oi": total_oi}


def option_stats(ticker: str, cfg) -> dict | None:
    """One symbol's chain aggregates, or None (fail-soft, warned by the caller loop)."""
    ua = "reddit-signal-radar/0.1 (open-source ticker signal bot)"
    raw = _get_json(CHAIN_URL.format(sym=ticker.upper()), ua)
    if raw is None:
        return None
    return parse_chain(raw)
