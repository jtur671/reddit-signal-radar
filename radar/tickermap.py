"""Ticker -> exact English Wikipedia article title, derived from Wikidata.

Names are not identifiers. Guessing an article from a company name resolved AAPL to
the fruit and SDGR to a dead physicist; for a pageviews ingest that is a silent,
permanent, wrong signal. This module fails CLOSED -- a ticker it cannot resolve gets
no title at all, which downstream renders as nothing.

The ticker lives on a QUALIFIER (pq:P249 on a p:P414 stock-exchange statement), not on
a direct property: the truthy wdt:P249 path has 38 statements, the qualifier path has
17,204. Every successful fetch is vendored to a data-branch snapshot, per cramer.py.
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import requests
import yaml

from radar import degrade

ENDPOINT = "https://query.wikidata.org/sparql"
UA = "reddit-signal-radar/0.1 (open-source ticker signal bot)"

# NYSE, Nasdaq, OTC Markets Group, NYSE American. Scoping is a correctness
# requirement, not an optimization: unscoped, ticker ambiguity is 15.2% and includes
# cross-domain collisions (BA -> Boeing / Bangkok Airways, DTE -> DTE Energy /
# Deutsche Telekom). US-scoped it is 3.6%, and every case is same-company-family.
EXCHANGES = ("wd:Q13677", "wd:Q82059", "wd:Q1930860", "wd:Q846626")

# Healthy measured count is 4,015. The COUNT(*) guard below only proves the live query
# and the count query AGREE -- it cannot tell they agree on a DEGRADED answer. If an
# EXCHANGES Q-id gets merged/redirected, or a triple pattern regresses, both queries
# return an equally-wrong small number and equality alone would vendor the breakage as
# truth. MIN_ROWS floors that: anything under a quarter of the healthy count is a
# broken query, not a shrinking stock market.
MIN_ROWS = 1000

_WHERE = """
  VALUES ?exch { %s }
  ?item p:P414 ?st .
  ?st ps:P414 ?exch .
  ?st pq:P249 ?ticker .
  ?st wikibase:rank ?rank .
  ?sl schema:about ?item ;
      schema:isPartOf <https://en.wikipedia.org/> ;
      schema:name ?enwiki .
  OPTIONAL { ?st pq:P582 ?end . }
""" % " ".join(EXCHANGES)

QUERY = "SELECT ?ticker ?item ?enwiki ?rank ?end WHERE {%s}" % _WHERE
COUNT_QUERY = "SELECT (COUNT(*) AS ?n) WHERE {%s}" % _WHERE

_DEPRECATED = "http://wikiba.se/ontology#DeprecatedRank"


def _val(binding, key):
    node = binding.get(key) if isinstance(binding, dict) else None
    return node.get("value") if isinstance(node, dict) else None


def parse_rows(raw) -> dict[str, str]:
    """{TICKER: exact article title}. Pure, never raises.

    Rules, in order: drop DeprecatedRank; drop statements whose end-date (pq:P582) is
    in the past when a non-ended alternative exists for that ticker; then accept only
    tickers left with exactly one distinct title. A ticker with two live same-family
    candidates is OMITTED, not guessed -- ticker_overrides.yml resolves those.

    Ticker/title values are coerced with str() so the dict[str, str] contract holds
    even when a binding value isn't already a string -- 'never raises' is this
    module's whole contract, and a bare .upper() on a non-string ticker used to break it."""
    try:
        bindings = raw["results"]["bindings"]
    except (TypeError, KeyError):
        return {}
    if not isinstance(bindings, list):
        return {}

    by_ticker: dict[str, list[tuple[str, bool]]] = {}
    for b in bindings:
        ticker, title = _val(b, "ticker"), _val(b, "enwiki")
        if not ticker or not title:
            continue
        if _val(b, "rank") == _DEPRECATED:
            continue
        by_ticker.setdefault(str(ticker).upper(), []).append((str(title), _val(b, "end") is not None))

    out: dict[str, str] = {}
    for ticker, rows in by_ticker.items():
        live = [t for t, ended in rows if not ended]
        candidates = live or [t for t, _ in rows]
        distinct = sorted(set(candidates))
        if len(distinct) == 1:
            out[ticker] = distinct[0]
    return out


def _get_json(query: str, ua: str, retries: int = 2, sleep_s: float = 1.0):
    """WDQS transport. Same retry shape as cramer._get_json. Never raises."""
    for attempt in range(retries):
        try:
            r = requests.get(ENDPOINT, params={"query": query, "format": "json"},
                             headers={"User-Agent": ua, "Accept": "application/sparql-results+json"},
                             timeout=90)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(sleep_s * (2 ** attempt)); continue
            return None
        except (requests.RequestException, ValueError):
            time.sleep(sleep_s * (2 ** attempt))
    return None


def load_overrides(path) -> dict[str, str]:
    """{TICKER: title} from the curated YAML. Pure, never raises."""
    try:
        doc = yaml.safe_load(Path(path).read_text()) or {}
        entries = doc.get("overrides") or {}
        out = {}
        for ticker, e in entries.items():
            title = e.get("title") if isinstance(e, dict) else e
            if title:
                out[str(ticker).upper()] = str(title)
        return out
    except (OSError, TypeError, ValueError, AttributeError, yaml.YAMLError):
        return {}


def _expected_rows(raw) -> int | None:
    try:
        return int(raw["results"]["bindings"][0]["n"]["value"])
    except (TypeError, KeyError, IndexError, ValueError):
        return None


def _snapshot_age_days(snap: Path, run_day: str) -> int | None:
    """Days between the snapshot's `fetched` stamp and run_day. None when either date
    is missing or unparseable — callers treat None as 'not fresh' and refresh."""
    try:
        doc = json.loads(snap.read_text())
        return (date.fromisoformat(run_day)
                - date.fromisoformat(str(doc["fetched"]))).days
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _snapshot_map(snap: Path) -> dict[str, str] | None:
    try:
        doc = json.loads(snap.read_text())
        m = doc.get("map")
        return m if isinstance(m, dict) else None
    except (OSError, ValueError, AttributeError):
        return None


def _snapshot_rows(snap: Path) -> int | None:
    """The previous snapshot's rows_fetched, for the regression guard against a query
    that silently shrinks. None when missing, unparseable, or predating this field."""
    try:
        doc = json.loads(snap.read_text())
        n = doc.get("rows_fetched")
        return int(n) if isinstance(n, (int, float)) else None
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def fetch_ticker_map(cfg, run_day: str, dry_run: bool = False) -> dict[str, str]:
    """Live fetch -> COUNT(*) validate -> vendor -> parse; snapshot fallback on outage
    or on a count/floor/regression refusal; {} + warn when both are gone. Overrides
    always win.

    The COUNT(*) check alone only proves the live query and the count query AGREE --
    it cannot tell they agree on a DEGRADED answer. MIN_ROWS and the regression check
    against the previous snapshot's rows_fetched catch that: a healthy fetch is never
    replaced by a much smaller one, even when the two queries are internally consistent.

    `dry_run` suppresses the snapshot WRITE only -- the fetch, the COUNT(*) check and
    every refusal path still run, so a dry run exercises the full code path without
    rewriting a file the scheduled job owns."""
    tc = getattr(cfg, "tickermap", None)
    snap = Path(getattr(tc, "snapshot_path", "data/ticker_articles.json"))
    # `or`, not just a getattr default: an `overrides_path:` key present but EMPTY
    # yields None, which the default never covers — and load_overrides(None) returns {}
    # rather than raising, so EVERY curated override (DOW, HTZ, SNOW, QQQ) would stop
    # applying silently while run.py's health floor, which already resolves it this way,
    # still counted 30 of them and lit the LED green. The two sites must agree.
    ov_path = getattr(tc, "overrides_path", None) or "radar/ticker_overrides.yml"
    max_age = int(getattr(tc, "max_age_days", 30))
    overrides = load_overrides(ov_path)

    def _finish(base: dict[str, str]) -> dict[str, str]:
        merged = dict(base)
        merged.update(overrides)      # curated wins unconditionally
        return merged

    def _refuse(reason: str) -> dict[str, str]:
        degrade.warn("tickermap", reason)
        cached = _snapshot_map(snap)
        return _finish(cached) if cached is not None else _finish({})

    # US listing churn is ~25/year against ~3,500 tickers, and the live query costs
    # ~22s. Refresh monthly, not daily. An unreadable date fails toward refreshing.
    fresh = _snapshot_map(snap)
    age = _snapshot_age_days(snap, run_day)
    if fresh is not None and age is not None and age < max_age:
        return _finish(fresh)

    raw = _get_json(QUERY, UA)
    bindings = None
    if isinstance(raw, dict):
        try:
            bindings = raw["results"]["bindings"]
        except (TypeError, KeyError):
            bindings = None

    if isinstance(bindings, list):
        expected = _expected_rows(_get_json(COUNT_QUERY, UA))
        n = len(bindings)
        # WDQS truncates silently at ~60s: HTTP 200, no error header, and the partial
        # response is cached for 5 minutes. Without this check a truncated map gets
        # vendored as truth and nothing ever notices.
        if expected is None or expected != n:
            return _refuse(f"row count {n} != expected {expected} — keeping snapshot")
        # Equality only proves the two queries agree with EACH OTHER, not that they
        # agree on a HEALTHY answer: a merged/redirected exchange Q-id or a regressed
        # triple pattern makes both queries agree on an equally-wrong small number.
        if n < MIN_ROWS:
            return _refuse(f"row count {n} under floor {MIN_ROWS} — keeping snapshot")
        prev_rows = _snapshot_rows(snap)
        if prev_rows is not None and n < prev_rows / 2:
            return _refuse(f"row count {n} under half of previous {prev_rows} — keeping snapshot")
        parsed = parse_rows(raw)
        if not dry_run:
            try:
                snap.parent.mkdir(parents=True, exist_ok=True)
                snap.write_text(json.dumps({"schema": 1, "fetched": run_day,
                                            "rows_fetched": n,
                                            "rows_expected": expected,
                                            "map": parsed}, sort_keys=True))
            except OSError as e:
                degrade.warn("tickermap snapshot write", e)
        return _finish(parsed)

    cached = _snapshot_map(snap)
    if cached is not None:
        degrade.warn("tickermap", "upstream unavailable — using vendored snapshot")
        return _finish(cached)
    degrade.warn("tickermap", "upstream and snapshot both unavailable")
    return _finish({})
