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
# The page walk exits on a SHORT page, which is a promise the endpoint makes and can
# break: one that ignores `offset` (or echoes full pages during an incident) would loop
# forever inside a scheduled job and hang the 6:17 AM publish until the runner times out.
# 10 x 5,000 = 50,000 rows against a measured 22,341-row settlement, so this is unreachable
# on healthy data and a loud breadcrumb when it is not.
MAX_PAGES = 10


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
    record_total is FINRA's `record-total` response header, a free CROSS-CHECK on the
    assembled row count. It is a courtesy, not a contract: FINRA can omit it, and a
    guard conditioned on its presence is a guard that can switch itself off, so
    _fetch_all_pages reports completeness independently. Returns (None, None) on any
    failure."""
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


def _fetch_all_pages(ua: str, page_size: int,
                     settlement: str) -> tuple[list | None, int | None, bool]:
    """Page until a short page (< page_size rows) confirms there is no more to fetch,
    scoped to `settlement` via an EQUAL compareFilter (see module docstring — without
    it FINRA walks its full unordered multi-million-row archive instead of the
    current settlement's ~22K rows).

    Returns (rows, record_total, complete). `rows` is None only when the very first
    page fails outright, so the caller can fall back to the snapshot rather than vendor
    a partial or empty universe.

    `complete` is the walk's own verdict, and it is stated rather than left to be
    inferred. It is True for exactly ONE exit — the short page, which is the endpoint
    saying there is nothing more — and False for a page that failed mid-walk, a page
    that came back as something other than a list, and the MAX_PAGES cap. The caller
    used to infer this from `record_total is not None`, and that inference is what let a
    missing `record-total` header silently disable the truncation guard: the header is a
    courtesy, the short page is a statement about THIS walk, and only one of them is
    always there.

    Bounded by MAX_PAGES rather than trusting the short page to arrive: the short-page
    exit is a promise the endpoint makes, and this runs unattended on a schedule. A
    capped walk is by definition partial; the warn below is the breadcrumb, and the
    False is what actually stops it being vendored."""
    rows: list = []
    total: int | None = None
    offset = 0
    for _ in range(MAX_PAGES):
        payload = {"limit": page_size, "offset": offset,
                   "compareFilters": [{"fieldName": "settlementDate",
                                        "fieldValue": settlement, "compareType": "EQUAL"}]}
        page, page_total = _post_json(URL, payload, ua)
        if page_total is not None:
            total = page_total
        if page is None:
            return (None, None, False) if offset == 0 else (rows, total, False)
        if not isinstance(page, list):
            return (rows if rows else None), total, False
        rows.extend(page)
        if len(page) < page_size:
            return rows, total, True
        offset += page_size
    degrade.warn("short interest feed",
                 f"page cap {MAX_PAGES} hit at offset {offset} — endpoint never sent a "
                 f"short page; treating the walk as incomplete")
    return rows, total, False


def _read_snapshot(snap: Path) -> tuple[dict[str, dict], str] | None:
    """Load the vendored snapshot and re-validate it -- re-filters the 999.99 clamp
    sentinel, since the snapshot rides the data branch and is the one input this
    module trusts unvalidated. None when the file is missing, unparseable, or
    malformed -- and a snapshot with rows but no settlement date IS malformed, see
    below."""
    try:
        doc = json.loads(snap.read_text())
    except (OSError, ValueError):
        return None
    rows = doc.get("rows") if isinstance(doc, dict) else None
    if not isinstance(rows, dict):
        return None
    # Rows without a settlement date are not undated data, they are NO data, so a
    # snapshot missing one is MALFORMED rather than merely thin. run.py gates its whole
    # board-assignment loop on `if si_as_of` — the number and its date travel together
    # or not at all — so serving (rows, "") renders zero days-to-cover anywhere while
    # `si_rows` stays non-empty and lights the finra_si LED green. Green LED, no data.
    # A partial write or a hand-edit of the vendored file is the realistic path, and it
    # rides the data branch, which is why this read re-validates at all.
    settlement = doc.get("settlement")
    if not isinstance(settlement, str) or not settlement.strip():
        return None
    clean = {t: r for t, r in rows.items()
             if isinstance(r, dict) and r.get("days_to_cover") != SENTINEL_DTC}
    return clean, settlement


def fetch_short_interest(cfg, run_day: str, dry_run: bool = False) -> tuple[dict[str, dict], str]:
    """Settlement-gated fetch -> vendor snapshot -> parse; snapshot fallback on outage
    or on a walk that cannot be VERIFIED complete (an incomplete page walk, or a
    row-count mismatch against `record-total`); ({}, "") + warn when both are gone. The
    snapshot rides the data branch and is refreshed only when the settlement date
    advances.

    `dry_run` suppresses the snapshot WRITE only -- discovery, the full page walk and
    the completeness guards all still run, so a dry run exercises the whole path without
    rewriting a file the scheduled job owns."""
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
        raw, total, complete = _fetch_all_pages(ua, page_size, latest)
        if raw:
            rows, settlement = parse_rows(raw)
            # A partial universe must not be vendored: it carries the CORRECT settlement
            # date, so it then matches the refresh gate above and is served for up to two
            # weeks. Same guard as the sibling tickermap task's COUNT(*) check.
            #
            # Two checks, and the walk's own verdict comes FIRST because it is the one
            # that always exists. `record-total` is a courtesy header; when FINRA omits
            # it, `total is not None` is False and the count check switches ITSELF off —
            # which is exactly how a mid-walk page failure used to vendor a truncated
            # universe. Refuse whenever the walk cannot be VERIFIED complete.
            refusal = None
            if rows and not complete:
                refusal = (f"page walk did not complete — {len(raw)} rows assembled, "
                           f"keeping snapshot")
            elif rows and total is not None and len(raw) != total:
                refusal = f"row count {len(raw)} != expected {total} — keeping snapshot"
            if refusal:
                degrade.warn("short interest feed", refusal)
                return cached if cached is not None else ({}, "")
            if rows:
                if not dry_run:
                    try:
                        text = json.dumps({"schema": 1, "settlement": settlement,
                                            "rows": rows}, sort_keys=True)
                        snap.parent.mkdir(parents=True, exist_ok=True)
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
