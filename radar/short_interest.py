"""FINRA consolidated short interest — days-to-cover as slow-moving context.

Source: `api.finra.org`'s consolidated short interest endpoint (keyless, POST,
`Accept: application/json`). Despite the `otcMarket` path it covers listed names too —
measured `marketClassCode` values include NNM, NYSE and ARCA, 22,341 symbols for
settlement 2026-07-31. Nasdaq's `api.nasdaq.com` endpoint returns identical figures
(verified on MVIS) but is one-ticker-per-request, comma-formatted, and blocked a
default curl UA with HTTP 000 — FINRA has no such bot posture. Twice-monthly
settlement cadence makes this an ideal vendoring case: every successful pull is
VENDORED to a data-branch snapshot, refreshed only when a new settlement date
appears, and the snapshot is the fallback when upstream disappears. This is
DISTINCT from the daily FINRA short *volume* already ingested by `radar/shorts.py`
(flow, not position) and never enters the composite — it ships as `as_of`-stamped
context only."""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from radar import degrade

URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
SENTINEL_DTC = 999.99      # zero average daily volume, not a real 999-day cover
PAGE = 5000                # FINRA's hard cap per request


def _post_json(url: str, payload: dict, ua: str, retries: int = 2, sleep_s: float = 1.0):
    for attempt in range(retries):
        try:
            r = requests.post(url, json=payload, headers={"User-Agent": ua,
                                                            "Accept": "application/json"},
                               timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503):
                time.sleep(sleep_s * (2 ** attempt)); continue
            return None
        except (requests.RequestException, ValueError):
            time.sleep(sleep_s * (2 ** attempt))
    return None


def _latest_settlement(ua: str) -> str | None:
    """One row, sorted by settlement date descending -> its settlementDate, or None."""
    payload = {"limit": 1, "sortFields": ["-settlementDate"]}
    rows = _post_json(URL, payload, ua)
    if not isinstance(rows, list) or not rows:
        return None
    row = rows[0]
    if not isinstance(row, dict):
        return None
    settlement = row.get("settlementDate")
    return str(settlement) if settlement else None


def parse_rows(raw) -> tuple[dict[str, dict], str]:
    """List of FINRA rows -> ({TICKER: {"days_to_cover": float, "shares": int}},
    settlement_date). Pure, never raises. Drops the 999.99 zero-ADV sentinel."""
    out: dict[str, dict] = {}
    settlement = ""
    if not isinstance(raw, list):
        return {}, ""
    for row in raw:
        if not isinstance(row, dict):
            continue
        sym = row.get("symbolCode")
        if not sym or not isinstance(sym, str):
            continue
        try:
            dtc = float(row.get("daysToCoverQuantity"))
            shares = int(row.get("currentShortPositionQuantity"))
        except (TypeError, ValueError):
            continue
        if dtc == SENTINEL_DTC:
            continue
        out[sym.upper()] = {"days_to_cover": dtc, "shares": shares}
        rd = row.get("settlementDate")
        if rd:
            settlement = str(rd)
    return out, settlement


def _fetch_all_pages(ua: str, page_size: int) -> list | None:
    """Page until a short page (< page_size rows) confirms there is no more to fetch.
    Returns None if the very first page fails, so the caller can fall back."""
    rows: list = []
    offset = 0
    while True:
        payload = {"limit": page_size, "offset": offset, "compareFilters": []}
        page = _post_json(URL, payload, ua)
        if page is None:
            return None if offset == 0 else rows
        if not isinstance(page, list):
            return rows if rows else None
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += page_size


def fetch_short_interest(cfg, run_day: str) -> tuple[dict[str, dict], str]:
    """Settlement-gated fetch -> vendor snapshot -> parse; snapshot fallback on
    outage; ({}, "") + warn when both are gone. The snapshot rides the data branch."""
    sc = getattr(cfg, "short_interest", None)
    snap = Path(getattr(sc, "snapshot_path", "data/short_interest.json"))
    page_size = int(getattr(sc, "page_size", PAGE))
    ua = "reddit-signal-radar/0.1 (open-source ticker signal bot)"

    cached: dict | None = None
    try:
        cached = json.loads(snap.read_text())
    except (OSError, ValueError):
        cached = None

    latest = _latest_settlement(ua)
    if latest is not None and cached and cached.get("settlement") == latest:
        return cached.get("rows", {}), latest

    if latest is not None:
        raw = _fetch_all_pages(ua, page_size)
        if raw:
            rows, settlement = parse_rows(raw)
            if rows:
                try:
                    text = json.dumps({"schema": 1, "settlement": settlement, "rows": rows},
                                       sort_keys=True)
                    if not snap.exists() or snap.read_text() != text:
                        snap.write_text(text)
                except OSError as e:
                    degrade.warn("short interest snapshot write", e)
                return rows, settlement

    if cached:
        degrade.warn("short interest feed", "upstream unavailable — using vendored snapshot")
        return cached.get("rows", {}), cached.get("settlement", "")

    degrade.warn("short interest feed", "upstream and snapshot both unavailable")
    return {}, ""
