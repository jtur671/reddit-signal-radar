"""FINRA consolidated short interest — days-to-cover as slow-moving context.

Source: `api.finra.org`'s consolidated short interest group (keyless, `Accept:
application/json`). Despite the `otcMarket` path it covers listed names too —
measured `marketClassCode` values include NNM, NYSE and ARCA, 22,341 symbols for
settlement 2026-07-31 (a per-settlement filtered count — see `_fetch_all_pages`).
Nasdaq's `api.nasdaq.com` endpoint returns identical figures (verified on MVIS) but is
one-ticker-per-request, comma-formatted, and blocked a default curl UA with HTTP 000 —
FINRA has no such bot posture. Twice-monthly settlement cadence makes this an ideal
vendoring case: every successful pull is VENDORED to a data-branch snapshot, refreshed
only when a new settlement date appears, and the snapshot is the fallback when
upstream disappears — and, since it is the one input this module trusts unvalidated,
it is re-filtered for the sentinel on every read. This is DISTINCT from the daily
FINRA short *volume* already ingested by `radar/shorts.py` (flow, not position) and
never enters the composite — it ships as `as_of`-stamped context only.

Two endpoints, two verbs, deliberately:
  - Settlement discovery is a GET against `/partitions/...` — one keyless request, no
    body. The obvious alternative (POST the data endpoint sorted by settlementDate
    descending, limit 1) is REJECTED by FINRA: measured HTTP 400, "Sorting is allowed
    only if all partition keys are specified in an EQUAL CompareFilter."
  - The data pull is POST against `/data/...`, and MUST carry an EQUAL compareFilter
    on settlementDate. Without it, FINRA does not scope the query to the current
    settlement — it walks its full archive (>3M rows, unordered by date; measured
    offset 0 -> settlement 2020-04-15, offset 3,000,000 -> settlement 2024-10-15) —
    which is slow, wrong, and can vendor a six-year-old position as current.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from radar import degrade

URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
PARTITIONS_URL = "https://api.finra.org/partitions/group/otcMarket/name/consolidatedShortInterest"

# Clamp at the maximum representable value, NOT a zero-average-daily-volume marker:
# measured, AACAF carries averageDailyVolumeQuantity 1331 (non-zero) alongside
# daysToCoverQuantity 999.99. Filtering it out is still correct -- a clamped value is
# no more a real day-count than a zero-ADV one -- but the reason is "hit the ceiling",
# not "divide by zero".
SENTINEL_DTC = 999.99
PAGE = 5000                # FINRA's hard cap per request


def _get_json(url: str, ua: str, retries: int = 2, sleep_s: float = 1.0):
    """GET transport for settlement discovery. Same retry shape as cramer._get_json."""
    for attempt in range(retries):
        try:
            r = requests.get(url, headers={"User-Agent": ua, "Accept": "application/json"},
                             timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503):
                time.sleep(sleep_s * (2 ** attempt)); continue
            return None
        except (requests.RequestException, ValueError):
            time.sleep(sleep_s * (2 ** attempt))
    return None


def _post_json(url: str, payload: dict, ua: str, retries: int = 2, sleep_s: float = 1.0):
    """POST transport for the data pull. Returns (rows, record_total) on a 200 —
    record_total is FINRA's `record-total` response header, the free guard against a
    page that fails mid-walk vendoring a truncated slice of the universe. Returns
    (None, None) on any failure."""
    for attempt in range(retries):
        try:
            r = requests.post(url, json=payload, headers={"User-Agent": ua,
                                                            "Accept": "application/json"},
                              timeout=30)
            if r.status_code == 200:
                total = r.headers.get("record-total")
                try:
                    total = int(total) if total is not None else None
                except (TypeError, ValueError):
                    total = None
                return r.json(), total
            if r.status_code in (429, 500, 502, 503):
                time.sleep(sleep_s * (2 ** attempt)); continue
            return None, None
        except (requests.RequestException, ValueError):
            time.sleep(sleep_s * (2 ** attempt))
    return None, None


def _latest_settlement(ua: str) -> str | None:
    """Newest settlement date via the partitions endpoint's `availablePartitions`
    (already newest-first) -- one keyless GET, no body. See the module docstring for
    why this replaces a sorted-POST discovery query FINRA rejects outright."""
    doc = _get_json(PARTITIONS_URL, ua)
    if not isinstance(doc, dict):
        return None
    partitions = doc.get("availablePartitions")
    if not isinstance(partitions, list) or not partitions:
        return None
    first = partitions[0]
    if not isinstance(first, dict):
        return None
    dates = first.get("partitions")
    if not isinstance(dates, list) or not dates or not dates[0]:
        return None
    return str(dates[0])


def parse_rows(raw) -> tuple[dict[str, dict], str]:
    """List of FINRA rows -> ({TICKER: {"days_to_cover": float, "shares": int}},
    settlement_date). Pure, never raises. Drops the 999.99 clamp sentinel."""
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


def _fetch_all_pages(ua: str, page_size: int, settlement: str) -> tuple[list | None, int | None]:
    """Page until a short page (< page_size rows) confirms there is no more to fetch,
    scoped to `settlement` via an EQUAL compareFilter (see module docstring — without
    it FINRA walks its full unordered multi-million-row archive instead of the
    current settlement's ~22K rows). Returns (rows, record_total); rows is None only
    when the very first page fails outright, so the caller can fall back to the
    snapshot rather than vendor a partial or empty universe."""
    rows: list = []
    total: int | None = None
    offset = 0
    while True:
        payload = {"limit": page_size, "offset": offset,
                   "compareFilters": [{"fieldName": "settlementDate",
                                        "fieldValue": settlement, "compareType": "EQUAL"}]}
        page, page_total = _post_json(URL, payload, ua)
        if page_total is not None:
            total = page_total
        if page is None:
            return (None, None) if offset == 0 else (rows, total)
        if not isinstance(page, list):
            return (rows if rows else None), total
        rows.extend(page)
        if len(page) < page_size:
            return rows, total
        offset += page_size


def _read_snapshot(snap: Path) -> tuple[dict[str, dict], str] | None:
    """Load the vendored snapshot and re-validate it -- re-filters the 999.99 clamp
    sentinel, since the snapshot rides the data branch and is the one input this
    module trusts unvalidated. None when the file is missing, unparseable, or
    malformed."""
    try:
        doc = json.loads(snap.read_text())
    except (OSError, ValueError):
        return None
    rows = doc.get("rows") if isinstance(doc, dict) else None
    if not isinstance(rows, dict):
        return None
    clean = {t: r for t, r in rows.items()
             if isinstance(r, dict) and r.get("days_to_cover") != SENTINEL_DTC}
    return clean, str(doc.get("settlement", ""))


def fetch_short_interest(cfg, run_day: str) -> tuple[dict[str, dict], str]:
    """Settlement-gated fetch -> vendor snapshot -> parse; snapshot fallback on
    outage or on a row-count mismatch; ({}, "") + warn when both are gone. The
    snapshot rides the data branch and is refreshed only when the settlement date
    advances."""
    sc = getattr(cfg, "short_interest", None)
    snap = Path(getattr(sc, "snapshot_path", "data/short_interest.json"))
    page_size = int(getattr(sc, "page_size", PAGE))
    ua = "reddit-signal-radar/0.1 (open-source ticker signal bot)"
    # run_day is unused: interface parity with fetch_cramer.

    cached = _read_snapshot(snap)

    latest = _latest_settlement(ua)
    if latest is not None and cached is not None and cached[1] == latest:
        return cached

    if latest is not None:
        raw, total = _fetch_all_pages(ua, page_size, latest)
        if raw:
            rows, settlement = parse_rows(raw)
            if rows and total is not None and len(raw) != total:
                # FINRA hands us the truncation guard for free: a page that fails or
                # comes back short mid-walk must not vendor a partial universe that
                # then short-circuits every run for up to two weeks. Same guard as
                # the sibling tickermap task's COUNT(*) check.
                degrade.warn("short interest feed",
                             f"row count {len(raw)} != expected {total} — keeping snapshot")
                return cached if cached is not None else ({}, "")
            if rows:
                try:
                    text = json.dumps({"schema": 1, "settlement": settlement, "rows": rows},
                                       sort_keys=True)
                    if not snap.exists() or snap.read_text() != text:
                        snap.write_text(text)
                except OSError as e:
                    degrade.warn("short interest snapshot write", e)
                return rows, settlement

    if cached is not None:
        degrade.warn("short interest feed", "upstream unavailable — using vendored snapshot")
        return cached

    degrade.warn("short interest feed", "upstream and snapshot both unavailable")
    return {}, ""
