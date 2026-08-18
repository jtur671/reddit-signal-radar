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

from radar import atomic, degrade

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


def _is_past(end_value, today) -> bool:
    """True only when this statement's pq:P582 end-date is strictly BEFORE the run day.

    Presence of an end-date is not enough, and that shortcut was a live bug: a planned
    delisting is recorded on Wikidata as a FUTURE P582 sitting on the statement that is
    still the CURRENT listing. Presence-testing drops it, and where the ticker also has
    a stale undated statement, that stale one is left as the sole survivor and resolves
    cleanly -- to the wrong article.

    A date ending TODAY is not past: a listing that ends today is still listed today.

    An unparseable end-date, or an unparseable run day, returns False -- the statement
    stays in play. That direction is deliberate. Keeping a statement can only ADD a
    candidate, and a ticker with two candidates is OMITTED (see below); dropping one
    instead hands the win to whatever survives. This module's whole premise is that a
    missing title is a non-event while a wrong one is silent permanent corruption, so
    the unjudgeable case must fail toward omission."""
    if end_value is None or today is None:
        return False
    try:
        # WDQS serves xsd:dateTime as "2016-01-01T00:00:00Z", sometimes with a leading
        # "+" on the year. Take the date half; fromisoformat rejects anything else.
        return date.fromisoformat(str(end_value).lstrip("+")[:10]) < today
    except (TypeError, ValueError):
        return False


def parse_rows(raw, run_day: str) -> dict[str, str]:
    """{TICKER: exact article title}, resolved as of `run_day`. Pure, never raises.

    Rules, in order: drop DeprecatedRank; drop statements whose end-date (pq:P582) is
    in the past when a non-ended alternative exists for that ticker; then accept only
    tickers left with exactly one distinct title. A ticker with two live same-family
    candidates is OMITTED, not guessed -- ticker_overrides.yml resolves those.

    `run_day` is what "in the past" is measured against -- see _is_past. Passing it in
    rather than reading a clock keeps this function pure and the rule testable at any
    date, which is the only way the future-end-date case can be pinned.

    Ticker/title values are coerced with str() so the dict[str, str] contract holds
    even when a binding value isn't already a string -- 'never raises' is this
    module's whole contract, and a bare .upper() on a non-string ticker used to break it."""
    try:
        bindings = raw["results"]["bindings"]
    except (TypeError, KeyError):
        return {}
    if not isinstance(bindings, list):
        return {}

    try:
        today = date.fromisoformat(str(run_day))
    except (TypeError, ValueError):
        today = None          # no judgeable run day -> nothing is ended; see _is_past

    by_ticker: dict[str, list[tuple[str, bool]]] = {}
    for b in bindings:
        ticker, title = _val(b, "ticker"), _val(b, "enwiki")
        if not ticker or not title:
            continue
        if _val(b, "rank") == _DEPRECATED:
            continue
        by_ticker.setdefault(str(ticker).upper(), []).append(
            (str(title), _is_past(_val(b, "end"), today)))

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
            # Strings only, never str(). An override wins UNCONDITIONALLY over the live
            # map, so `str()`-ing a non-scalar fabricates a title that cannot exist
            # (`AAPL: [1, 2]` -> `"[1, 2]"`) and replaces a correct, verified one with a
            # guaranteed pageviews miss. Same premise as parse_rows: no title beats a
            # wrong one, so a typo'd entry is dropped rather than coerced.
            if not isinstance(title, str) or not title:
                continue
            out[str(ticker).upper()] = title
        return out
    except (OSError, TypeError, ValueError, AttributeError, yaml.YAMLError):
        return {}


def _expected_rows(raw) -> int | None:
    """The COUNT(*) answer, or None when it cannot be read as a whole number.

    OverflowError is in the tuple because `json.loads` accepts `Infinity`, `NaN` and
    `1e309` BY DEFAULT — simplejson is not installed, so `requests.json()` is the stdlib
    parser — and `int(float("inf"))` raises OverflowError, an ArithmeticError that
    ValueError does not cover. Measured escaping to main(): a WDQS count of `1e309`
    killed the whole publish, where every other unreadable count is a documented refusal."""
    try:
        return int(raw["results"]["bindings"][0]["n"]["value"])
    except (TypeError, KeyError, IndexError, ValueError, OverflowError):
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
        # `isinstance(True, int)` is True in Python, so a `rows_fetched: true` in the
        # vendored file used to read as 1 — which makes the 50% regression guard below
        # satisfiable by ANY fetch of one row or more. A guard a malformed field can
        # switch off is not a guard. OverflowError for the same reason as
        # _expected_rows: this file rides the data branch and `1e309` parses to inf.
        if isinstance(n, bool) or not isinstance(n, (int, float)):
            return None
        return int(n)
    except (OSError, ValueError, AttributeError, TypeError, OverflowError):
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
    rewriting a file the scheduled job owns.

    The top-level `except Exception` is a BACKSTOP, not a policy: every branch below has
    its own specific handler and its own documented refusal, and those are what should
    fire. But this function gates the 6:17 AM publish, and the two bugs that actually
    took the board down -- `Path(None)` from an empty config key, and `int(inf)` from a
    JSON `1e309` -- were both exceptions nobody had thought to name. No config typo or
    upstream novelty gets to do that again."""
    try:
        return _fetch_ticker_map(cfg, run_day, dry_run)
    except Exception as e:                       # noqa: BLE001 -- deliberate backstop
        degrade.warn("tickermap", e)
        return {}


def _fetch_ticker_map(cfg, run_day: str, dry_run: bool) -> dict[str, str]:
    """The real body of fetch_ticker_map; see that function for the contract."""
    tc = getattr(cfg, "tickermap", None)
    # `or`, not a bare getattr default, on EVERY key -- see the overrides_path note
    # below. A key present but EMPTY in config.yaml yields None through the real loader,
    # and getattr's default only fires when the ATTRIBUTE is absent: `Path(None)` and
    # `int(None)` both raise TypeError out of a fetcher documented as fail-soft.
    snap = Path(getattr(tc, "snapshot_path", None) or "data/ticker_articles.json")
    # `or`, not just a getattr default: an `overrides_path:` key present but EMPTY
    # yields None, which the default never covers — and load_overrides(None) returns {}
    # rather than raising, so EVERY curated override (DOW, HTZ, SNOW, QQQ) would stop
    # applying silently while run.py's health floor, which already resolves it this way,
    # still counted 30 of them and lit the LED green. The two sites must agree.
    ov_path = getattr(tc, "overrides_path", None) or "radar/ticker_overrides.yml"
    max_age = int(getattr(tc, "max_age_days", None) or 30)
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
    # `0 <=`, not just `< max_age`: a NEGATIVE age means the snapshot claims to have been
    # fetched in the FUTURE, and every negative number satisfies `age < max_age`. Measured
    # -26,435 for a 2099 stamp -- 72 years of serving an unrefreshed map, silently. Clock
    # skew on the runner or a hand-edit of the data branch produces it, so it is not
    # freshness, it is a broken clock, and it refreshes AND says so.
    if age is not None and age < 0:
        degrade.warn("tickermap",
                     f"snapshot is dated {-age} days in the FUTURE — the clock or the "
                     f"data branch is wrong; refreshing rather than trusting it")
    elif fresh is not None and age is not None and 0 <= age < max_age:
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
        parsed = parse_rows(raw, run_day)
        if not dry_run:
            try:
                # atomic.write_text, not Path.write_text: a bare write is
                # truncate-then-write, and a reader arriving mid-write sees a half-file
                # (measured 87% torn reads for _snapshot_map). ValueError is in the tuple
                # beside OSError because encode/decode errors are ValueErrors, not OSErrors
                # -- the exact gap that made short_interest's write path crash the publish.
                atomic.write_text(snap, json.dumps({"schema": 1, "fetched": run_day,
                                                    "rows_fetched": n,
                                                    "rows_expected": expected,
                                                    "map": parsed}, sort_keys=True))
            except (OSError, ValueError) as e:
                degrade.warn("tickermap snapshot write", e)
        return _finish(parsed)

    cached = _snapshot_map(snap)
    if cached is not None:
        degrade.warn("tickermap", "upstream unavailable — using vendored snapshot")
        return _finish(cached)
    degrade.warn("tickermap", "upstream and snapshot both unavailable")
    return _finish({})
