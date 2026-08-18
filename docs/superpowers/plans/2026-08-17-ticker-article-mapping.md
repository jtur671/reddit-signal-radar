# E2a — Ticker→Article Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `radar/about.py`'s company-name guessing with a Wikidata-derived exact-title map, so a ticker resolves to the right Wikipedia article or to nothing at all.

**Architecture:** A new `radar/tickermap.py` fetches ticker→article pairs from the Wikidata SPARQL endpoint, validates the result against an independent `COUNT(*)` before vendoring it to a data-branch snapshot, and merges a small curated override file that wins unconditionally. `radar/about.py` becomes a pure consumer of exact titles and loses every name-guessing and fuzzy path.

**Tech Stack:** Python 3.12, `requests`, `PyYAML`, pytest with `monkeypatch`. No new dependencies beyond what `requirements.txt` already pins (`PyYAML` is already present via `radar/config.py`).

**Spec:** `docs/superpowers/specs/2026-08-17-ticker-article-mapping-design.md`

## Global Constraints

- **The test suite is hermetic as of `b6b90ad` and must stay that way.** No test may open a socket. Verify with `PYTHONPATH=<scratchpad> python -m pytest -q -p nonet` where `nonet` is a plugin that raises on `socket.getaddrinfo`.
- **House stubbing style is `monkeypatch.setattr(module, "_private_helper", lambda ...)`.** `unittest.mock` is not used anywhere in this repo — do not introduce it.
- **Every source fails soft and reports itself.** A fetch failure yields a fallback value plus `degrade.warn(...)`, never a raised exception and never a failed run.
- **Fixtures live in `tests/fixtures/` and are read with `Path(...).read_text()`.**
- **Never guess a Wikipedia title.** Override → snapshot → nothing. No fuzzy search, no opensearch, no name-based lookup. This is the entire point of the change.
- Run tests with `source .venv/bin/activate && python -m pytest -q`.
- Do not commit to `main`. Work on the current branch.

---

### Task 1: `parse_rows` — pure SPARQL result → ticker→title map

**Files:**
- Create: `radar/tickermap.py`
- Create: `tests/test_tickermap.py`
- Create: `tests/fixtures/wikidata_rows.json`

**Interfaces:**
- Consumes: nothing.
- Produces: `parse_rows(raw: dict) -> dict[str, str]` — takes a WDQS JSON response, returns `{TICKER: "Exact Article Title"}`. Pure, never raises.

WDQS returns `{"results": {"bindings": [ {...}, ... ]}}`. Each binding looks like:

```json
{"ticker": {"value": "AAPL"},
 "item":   {"value": "http://www.wikidata.org/entity/Q312"},
 "enwiki": {"value": "Apple Inc."},
 "rank":   {"value": "http://wikiba.se/ontology#NormalRank"},
 "end":    {"value": "2016-01-01T00:00:00Z"}}
```

`end` is absent when the listing is current. `rank` is one of `PreferredRank`, `NormalRank`, `DeprecatedRank`.

- [ ] **Step 1: Write the fixture**

Create `tests/fixtures/wikidata_rows.json` covering every rule in one file:

```json
{"results": {"bindings": [
  {"ticker": {"value": "AAPL"}, "item": {"value": "http://www.wikidata.org/entity/Q312"},
   "enwiki": {"value": "Apple Inc."}, "rank": {"value": "http://wikiba.se/ontology#NormalRank"}},

  {"ticker": {"value": "AAL"}, "item": {"value": "http://www.wikidata.org/entity/Q1"},
   "enwiki": {"value": "Anglo American plc"}, "rank": {"value": "http://wikiba.se/ontology#DeprecatedRank"}},
  {"ticker": {"value": "AAL"}, "item": {"value": "http://www.wikidata.org/entity/Q2"},
   "enwiki": {"value": "American Airlines Group"}, "rank": {"value": "http://wikiba.se/ontology#NormalRank"}},

  {"ticker": {"value": "GOOG"}, "item": {"value": "http://www.wikidata.org/entity/Q95"},
   "enwiki": {"value": "Google"}, "rank": {"value": "http://wikiba.se/ontology#NormalRank"},
   "end": {"value": "2016-01-01T00:00:00Z"}},
  {"ticker": {"value": "GOOG"}, "item": {"value": "http://www.wikidata.org/entity/Q20800404"},
   "enwiki": {"value": "Alphabet Inc."}, "rank": {"value": "http://wikiba.se/ontology#NormalRank"}},

  {"ticker": {"value": "BBBY"}, "item": {"value": "http://www.wikidata.org/entity/Q813782"},
   "enwiki": {"value": "Bed Bath & Beyond"}, "rank": {"value": "http://wikiba.se/ontology#NormalRank"},
   "end": {"value": "2023-09-29T00:00:00Z"}},

  {"ticker": {"value": "DOW"}, "item": {"value": "http://www.wikidata.org/entity/Q3"},
   "enwiki": {"value": "Dow Chemical Company"}, "rank": {"value": "http://wikiba.se/ontology#NormalRank"}},
  {"ticker": {"value": "DOW"}, "item": {"value": "http://www.wikidata.org/entity/Q4"},
   "enwiki": {"value": "Dow Inc."}, "rank": {"value": "http://wikiba.se/ontology#NormalRank"}}
]}}
```

- [ ] **Step 2: Write the failing tests**

```python
import json
from pathlib import Path

import radar.tickermap as tm

RAW = json.loads(Path("tests/fixtures/wikidata_rows.json").read_text())


def test_plain_row_maps_ticker_to_title():
    assert tm.parse_rows(RAW)["AAPL"] == "Apple Inc."


def test_deprecated_rank_is_dropped():
    """AAL has a DeprecatedRank row for Anglo American; the live row must win."""
    assert tm.parse_rows(RAW)["AAL"] == "American Airlines Group"


def test_past_end_date_dropped_when_a_live_alternative_exists():
    """Google's listing ended 2016-01-01 and Alphabet's has no end date."""
    assert tm.parse_rows(RAW)["GOOG"] == "Alphabet Inc."


def test_sole_statement_is_kept_even_when_ended():
    """The proviso: an ended statement survives when it is the ONLY one for that
    ticker. Without this, every historical-only listing silently vanishes."""
    assert tm.parse_rows(RAW)["BBBY"] == "Bed Bath & Beyond"


def test_unresolved_same_family_ambiguity_is_omitted_not_guessed():
    """DOW has two live, same-rank candidates. parse_rows must NOT pick one at
    random -- the override file is what resolves these."""
    assert "DOW" not in tm.parse_rows(RAW)


def test_parse_rows_never_raises_on_junk():
    for junk in (None, {}, {"results": {}}, {"results": {"bindings": "nope"}},
                 {"results": {"bindings": [{"ticker": {}}]}}):
        assert tm.parse_rows(junk) == {}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_tickermap.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'radar.tickermap'`

- [ ] **Step 4: Write the implementation**

```python
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
    candidates is OMITTED, not guessed -- ticker_overrides.yml resolves those."""
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
        by_ticker.setdefault(ticker.upper(), []).append((title, _val(b, "end") is not None))

    out: dict[str, str] = {}
    for ticker, rows in by_ticker.items():
        live = [t for t, ended in rows if not ended]
        candidates = live or [t for t, _ in rows]
        distinct = sorted(set(candidates))
        if len(distinct) == 1:
            out[ticker] = distinct[0]
    return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_tickermap.py -q`
Expected: PASS, 6 tests.

- [ ] **Step 6: Commit**

```bash
git add radar/tickermap.py tests/test_tickermap.py tests/fixtures/wikidata_rows.json
git commit -m "feat(tickermap): parse Wikidata ticker->article rows

Qualifier path (p:P414/pq:P249), US-scoped. Drops DeprecatedRank and
past-end-dated statements when a live alternative exists, and omits
rather than guesses when two live candidates remain."
```

---

### Task 2: `fetch_ticker_map` — vendored fetch with the truncation guard

**Files:**
- Modify: `radar/tickermap.py`
- Modify: `tests/test_tickermap.py`

**Interfaces:**
- Consumes: `parse_rows` from Task 1.
- Produces:
  - `_get_json(query: str, ua: str, retries: int = 2, sleep_s: float = 1.0) -> dict | None` — private transport, the stub seam for tests.
  - `fetch_ticker_map(cfg, run_day: str) -> dict[str, str]` — fail-soft; live fetch → validate → vendor → parse, snapshot fallback, `{}` + warn when both gone.

**This task exists because of one measured behavior:** WDQS silently truncates at ~60s, returning **HTTP 200 with no error header** and `cache-control: max-age=300`, so the partial result is cached and re-served. A measured run returned 440 rows instead of 4,015 and looked perfectly healthy. A truncated snapshot is indistinguishable from a good one by inspection.

- [ ] **Step 1: Write the failing tests**

```python
def _resp(n_rows, count=None):
    """A WDQS response with n_rows bindings, and a COUNT that may disagree."""
    rows = [{"ticker": {"value": f"T{i}"}, "enwiki": {"value": f"Title {i}"},
             "rank": {"value": "http://wikiba.se/ontology#NormalRank"}}
            for i in range(n_rows)]
    return rows, {"results": {"bindings": [
        {"n": {"value": str(count if count is not None else n_rows)}}]}}


def test_row_count_mismatch_refuses_to_overwrite_snapshot(monkeypatch, tmp_path):
    """The whole point of this task. A truncated 200 must not be vendored."""
    snap = tmp_path / "ticker_articles.json"
    snap.write_text(json.dumps({"schema": 1, "fetched": "2026-08-01", "rows_fetched": 3,
                                "rows_expected": 3, "map": {"OLD": "Old Title"}}))
    rows, count = _resp(2, count=4015)          # truncated: 2 returned, 4015 expected

    def fake_get(query, ua, **kw):
        return count if "COUNT" in query else {"results": {"bindings": rows}}

    monkeypatch.setattr(tm, "_get_json", fake_get)
    cfg = _cfg(tmp_path)
    got = tm.fetch_ticker_map(cfg, "2026-08-17")

    assert got == {"OLD": "Old Title"}, "must serve the old snapshot, not the truncated fetch"
    assert json.loads(snap.read_text())["map"] == {"OLD": "Old Title"}, "snapshot unchanged"
    assert any("row count" in str(e).lower() for e in degrade.events())


def test_matching_count_vendors_the_snapshot(monkeypatch, tmp_path):
    snap = tmp_path / "ticker_articles.json"
    rows, count = _resp(3)
    monkeypatch.setattr(tm, "_get_json",
                        lambda q, ua, **kw: count if "COUNT" in q else {"results": {"bindings": rows}})
    got = tm.fetch_ticker_map(_cfg(tmp_path), "2026-08-17")
    assert got["T0"] == "Title 0"
    written = json.loads(snap.read_text())
    assert written["rows_fetched"] == written["rows_expected"] == 3
    assert written["fetched"] == "2026-08-17"


def test_upstream_down_serves_snapshot_and_warns(monkeypatch, tmp_path):
    snap = tmp_path / "ticker_articles.json"
    snap.write_text(json.dumps({"schema": 1, "map": {"AAPL": "Apple Inc."}}))
    monkeypatch.setattr(tm, "_get_json", lambda *a, **k: None)
    assert tm.fetch_ticker_map(_cfg(tmp_path), "2026-08-17") == {"AAPL": "Apple Inc."}
    assert any("snapshot" in str(e).lower() for e in degrade.events())


def test_both_gone_returns_empty_and_warns(monkeypatch, tmp_path):
    monkeypatch.setattr(tm, "_get_json", lambda *a, **k: None)
    assert tm.fetch_ticker_map(_cfg(tmp_path), "2026-08-17") == {}
    assert degrade.events()


def test_fresh_snapshot_skips_the_fetch_entirely(monkeypatch, tmp_path):
    """Spec 2.7: refresh only when the snapshot is older than max_age_days. Listing
    churn is <1%/yr, and the live query costs ~22s -- paying that daily is waste."""
    snap = tmp_path / "ticker_articles.json"
    snap.write_text(json.dumps({"schema": 1, "fetched": "2026-08-10",
                                "map": {"AAPL": "Apple Inc."}}))
    calls = []
    monkeypatch.setattr(tm, "_get_json", lambda *a, **k: calls.append(1))
    got = tm.fetch_ticker_map(_cfg(tmp_path), "2026-08-17")   # 7 days old, max_age 30
    assert calls == [], "a fresh snapshot must not trigger a network call"
    assert got["AAPL"] == "Apple Inc."


def test_stale_snapshot_triggers_a_refresh(monkeypatch, tmp_path):
    snap = tmp_path / "ticker_articles.json"
    snap.write_text(json.dumps({"schema": 1, "fetched": "2026-06-01",
                                "map": {"AAPL": "Stale Title"}}))
    rows, count = _resp(1)
    rows[0] = {"ticker": {"value": "AAPL"}, "enwiki": {"value": "Apple Inc."},
               "rank": {"value": "http://wikiba.se/ontology#NormalRank"}}
    monkeypatch.setattr(tm, "_get_json",
                        lambda q, ua, **kw: count if "COUNT" in q else {"results": {"bindings": rows}})
    got = tm.fetch_ticker_map(_cfg(tmp_path), "2026-08-17")   # 77 days old
    assert got["AAPL"] == "Apple Inc."


def test_unparseable_fetched_date_forces_a_refresh(monkeypatch, tmp_path):
    """Fail toward doing the work, not toward silently serving a snapshot forever."""
    snap = tmp_path / "ticker_articles.json"
    snap.write_text(json.dumps({"schema": 1, "fetched": "garbage", "map": {"A": "B"}}))
    calls = []
    monkeypatch.setattr(tm, "_get_json", lambda *a, **k: calls.append(1) or None)
    tm.fetch_ticker_map(_cfg(tmp_path), "2026-08-17")
    assert calls, "an unreadable date must not be treated as fresh"


def test_overrides_beat_the_snapshot(monkeypatch, tmp_path):
    ov = tmp_path / "ov.yml"
    ov.write_text('overrides:\n  DOW: {title: "Dow Inc.", why: "same-family"}\n')
    rows, count = _resp(1)
    rows[0] = {"ticker": {"value": "DOW"}, "enwiki": {"value": "Dow Chemical Company"},
               "rank": {"value": "http://wikiba.se/ontology#NormalRank"}}
    monkeypatch.setattr(tm, "_get_json",
                        lambda q, ua, **kw: count if "COUNT" in q else {"results": {"bindings": rows}})
    cfg = _cfg(tmp_path, overrides=str(ov))
    assert tm.fetch_ticker_map(cfg, "2026-08-17")["DOW"] == "Dow Inc."
```

Add these helpers at the top of the test file:

```python
import types
from radar import degrade


def _cfg(tmp_path, overrides="radar/ticker_overrides.yml"):
    return types.SimpleNamespace(tickermap=types.SimpleNamespace(
        snapshot_path=str(tmp_path / "ticker_articles.json"),
        overrides_path=overrides, max_age_days=30))


@pytest.fixture(autouse=True)
def _clear_degrade():
    degrade.clear() if hasattr(degrade, "clear") else None
    yield
```

If `radar/degrade.py` has no `clear()`, read the module and use whatever reset the existing tests use — check `tests/test_health.py` for the established pattern and copy it rather than inventing one.

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_tickermap.py -q`
Expected: FAIL — `AttributeError: module 'radar.tickermap' has no attribute 'fetch_ticker_map'`

- [ ] **Step 3: Write the implementation**

Append to `radar/tickermap.py`:

```python
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
    except (OSError, ValueError, AttributeError, yaml.YAMLError):
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


def fetch_ticker_map(cfg, run_day: str) -> dict[str, str]:
    """Live fetch -> COUNT(*) validate -> vendor -> parse; snapshot fallback on outage
    or on a count mismatch; {} + warn when both are gone. Overrides always win."""
    tc = getattr(cfg, "tickermap", None)
    snap = Path(getattr(tc, "snapshot_path", "data/ticker_articles.json"))
    ov_path = getattr(tc, "overrides_path", "radar/ticker_overrides.yml")
    max_age = int(getattr(tc, "max_age_days", 30))
    overrides = load_overrides(ov_path)

    def _finish(base: dict[str, str]) -> dict[str, str]:
        merged = dict(base)
        merged.update(overrides)      # curated wins unconditionally
        return merged

    # US listing churn is ~25/year against ~3,500 tickers, and the live query costs
    # ~22s. Refresh monthly, not daily. An unreadable date fails toward refreshing.
    fresh = _snapshot_map(snap)
    if fresh is not None and _snapshot_age_days(snap, run_day) is not None \
            and _snapshot_age_days(snap, run_day) < max_age:
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
        # WDQS truncates silently at ~60s: HTTP 200, no error header, and the partial
        # response is cached for 5 minutes. Without this check a truncated map gets
        # vendored as truth and nothing ever notices.
        if expected is None or expected != len(bindings):
            degrade.warn("tickermap",
                         f"row count {len(bindings)} != expected {expected} — keeping snapshot")
            cached = _snapshot_map(snap)
            if cached is not None:
                return _finish(cached)
            return _finish({})
        parsed = parse_rows(raw)
        try:
            snap.parent.mkdir(parents=True, exist_ok=True)
            snap.write_text(json.dumps({"schema": 1, "fetched": run_day,
                                        "rows_fetched": len(bindings),
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_tickermap.py -q`
Expected: PASS, 11 tests.

- [ ] **Step 5: Verify hermeticity**

Run the whole suite under the socket blocker (see Global Constraints). Expected: 0 DNS lookups.

- [ ] **Step 6: Commit**

```bash
git add radar/tickermap.py tests/test_tickermap.py
git commit -m "feat(tickermap): vendored fetch with a COUNT(*) truncation guard

WDQS truncates silently at ~60s -- HTTP 200, no error header, and the
partial result is cached for 5 minutes. A measured run returned 440 rows
instead of 4015 and looked healthy. Validate against an independent
COUNT(*) before vendoring, and keep the old snapshot on mismatch."
```

---

### Task 3: The curated override file

**Files:**
- Create: `radar/ticker_overrides.yml`
- Create: `tests/fixtures/override_titles.json`
- Modify: `tests/test_tickermap.py`

**Interfaces:**
- Consumes: `load_overrides` from Task 2.
- Produces: the data file that resolves the 9 same-family ambiguities and the 23 holding-company splits.

**The file content is supplied separately** — it is generated and API-verified by a research pass, and lands in the scratchpad as `ticker_overrides_draft.yml`. Copy it in verbatim; do not invent entries. If it is not present, stop and ask rather than guessing titles.

- [ ] **Step 1: Write the failing test**

```python
def test_every_override_title_is_verified():
    """A typo'd override is a wrong-entity bug of exactly the kind this subsystem
    exists to eliminate, so pin every title against the verified fixture rather than
    trusting the YAML. Regenerate the fixture only alongside a fresh API check."""
    verified = json.loads(Path("tests/fixtures/override_titles.json").read_text())
    got = tm.load_overrides("radar/ticker_overrides.yml")
    assert got, "override file must not be empty"
    for ticker, title in got.items():
        assert ticker in verified, f"{ticker} is not in the verified fixture"
        assert title == verified[ticker], f"{ticker}: {title!r} != verified {verified[ticker]!r}"


def test_every_override_has_a_reason():
    """`why` is what makes the file reviewable a year from now."""
    doc = yaml.safe_load(Path("radar/ticker_overrides.yml").read_text())
    for ticker, entry in doc["overrides"].items():
        assert entry.get("why"), f"{ticker} has no `why`"
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL — the override file does not exist yet.

- [ ] **Step 3: Add the data files**

Copy the verified YAML to `radar/ticker_overrides.yml`. Derive `tests/fixtures/override_titles.json` from it as a flat `{"TICKER": "Title"}` map.

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_tickermap.py -q`

- [ ] **Step 5: Commit**

```bash
git add radar/ticker_overrides.yml tests/fixtures/override_titles.json tests/test_tickermap.py
git commit -m "feat(tickermap): curated overrides for splits and same-family ties

Every title verified against the Wikipedia REST and pageviews APIs.
Overrides are source, not state, so they live on main under review."
```

---

### Task 4: `about.py` consumes exact titles

**Files:**
- Modify: `radar/about.py`
- Modify: `tests/test_about.py`

**Interfaces:**
- Consumes: `fetch_ticker_map` output — a `dict[str, str]`.
- Produces:
  - `fetch_summary(title: str, ua: str) -> dict | None` — unchanged signature, but the argument is now an **exact article title**, never a company name.
  - `describe(ticker: str, name: str, title: str | None, cache: dict, ua: str) -> dict` — **signature change**: gains `title`. `name` remains for display only.
  - `load_cache(path) -> dict` / `save_cache(path, cache)` — now schema-versioned.

`describe`'s cache entry shape is unchanged: `{"name": str, "desc": str, "extract": str}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_unmapped_ticker_makes_no_request(monkeypatch):
    """The anti-fuzzy guarantee. A ticker with no title must not fall back to a
    name-based lookup -- that is what resolved AAPL to the fruit. Assert on the CALL
    COUNT, not just the return value: a None return could also mean 'fetched and
    missed', which is a different and much worse behavior."""
    calls = []
    monkeypatch.setattr(about, "fetch_summary", lambda *a, **k: calls.append(a) or None)
    cache = {}
    entry = about.describe("MVIS", "MicroVision", None, cache)
    assert calls == [], "no title must mean no request"
    assert entry == {"name": "MicroVision", "desc": "", "extract": ""}


def test_exact_title_is_what_gets_fetched(monkeypatch):
    seen = {}
    def fake(title, ua="x"):
        seen["title"] = title
        return {"desc": "American multinational technology company", "extract": "..."}
    monkeypatch.setattr(about, "fetch_summary", fake)
    about.describe("AAPL", "Apple", "Apple Inc.", {})
    assert seen["title"] == "Apple Inc.", "must fetch the mapped title, not the company name"


def test_cache_with_stale_schema_is_discarded(tmp_path):
    p = tmp_path / "about.json"
    p.write_text(json.dumps({"schema": 0, "entries": {"AAPL": {"name": "Apple",
                                                               "desc": "Edible fruit"}}}))
    assert about.load_cache(p) == {}, "a poisoned cache must not survive the fix"


def test_cache_without_schema_is_discarded(tmp_path):
    """The live data-branch cache predates schema versioning and holds 34 wrong-entity
    entries. They are cache HITS, so they never self-heal -- they must be dropped."""
    p = tmp_path / "about.json"
    p.write_text(json.dumps({"AAPL": {"name": "Apple", "desc": "Edible fruit"}}))
    assert about.load_cache(p) == {}


def test_current_schema_round_trips(tmp_path):
    p = tmp_path / "about.json"
    about.save_cache(p, {"AAPL": {"name": "Apple", "desc": "tech company", "extract": ""}})
    assert about.load_cache(p)["AAPL"]["desc"] == "tech company"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_about.py -q`
Expected: FAIL — `describe()` takes 4 positional arguments but 5 were given.

- [ ] **Step 3: Rewrite `radar/about.py`**

Replace the module docstring and the `load_cache` / `save_cache` / `describe` functions:

```python
"""Company descriptions for the detail modal — 'what is HPE and why should I care'.

yfinance/.info is 429-blocked from cloud IPs, so we use Wikipedia's free, no-auth REST
summary API. The article title comes from radar/tickermap.py as an EXACT title; this
module never guesses one from a company name. It used to, and the result was AAPL ->
"Apple" -> "Edible fruit" on 13.7% of the board. A ticker with no mapping gets no
description — that is the correct outcome, not a gap to paper over.
"""

SCHEMA = 1


def load_cache(path) -> dict:
    """Entries for the current schema only. A cache written by an older schema is
    discarded wholesale: the pre-SCHEMA-1 file holds wrong-entity entries that are
    cache HITS, so they would never re-fetch and never heal."""
    try:
        doc = json.loads(Path(path).read_text())
    except Exception:
        return {}
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        return {}
    entries = doc.get("entries")
    return entries if isinstance(entries, dict) else {}


def save_cache(path, cache: dict) -> None:
    Path(path).write_text(json.dumps({"schema": SCHEMA, "entries": cache}, sort_keys=True))


def describe(ticker: str, name: str, title: str | None, cache: dict,
             ua: str = "reddit-signal-radar/0.1") -> dict:
    """Return {name, desc, extract} for a ticker. `title` is the exact Wikipedia
    article title from the ticker map, or None when the ticker is unmapped — in which
    case NO request is made. Mutates `cache` so the caller can persist new entries."""
    cached = cache.get(ticker)
    if cached is not None:
        return cached
    summary = (fetch_summary(title, ua) or {}) if title else {}
    entry = {"name": name or ticker, "desc": summary.get("desc", ""),
             "extract": summary.get("extract", "")}
    cache[ticker] = entry
    return entry
```

Also update `fetch_summary`'s docstring and parameter name from `name` to `title`, and its `warn` label from `f"wikipedia {name}"` to `f"wikipedia {title}"`. Its body is otherwise unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_about.py -q`

- [ ] **Step 5: Run the full suite**

Run: `source .venv/bin/activate && python -m pytest -q`
Expected: FAIL in `tests/test_run_*.py` — `run.py` still calls `describe` with the old signature. That is Task 5. Do not fix it here; note it and move on.

- [ ] **Step 6: Commit**

```bash
git add radar/about.py tests/test_about.py
git commit -m "feat(about): consume exact article titles, delete name guessing

describe() gains an explicit title argument and makes NO request when it
is None. Cache is schema-versioned so the live data-branch file -- which
holds 34 wrong-entity entries that are cache hits and would never
self-heal -- is discarded rather than merged."
```

---

### Task 5: Wire it into the run

**Files:**
- Modify: `radar/run.py:38` (`_enrich_ticker`), `:76-82` (the enrich block), `:163-171` (`sources`)
- Modify: `config.yaml`
- Modify: `tests/conftest.py`
- Modify: `tests/test_run_smoke.py`

**Interfaces:**
- Consumes: `tickermap.fetch_ticker_map(cfg, run_day) -> dict[str, str]`, `about.describe(ticker, name, title, cache, ua)`.
- Produces: a `tickermap` entry in `health.json`'s `sources` block.

- [ ] **Step 1: Add the config block**

In `config.yaml`, after the `cramer:` block:

```yaml
# Ticker -> exact Wikipedia article title, from Wikidata (p:P414/pq:P249, US exchanges).
# Refreshed only when the vendored snapshot is older than max_age_days: US listing churn
# is ~25/year against ~3,500 tickers (<1%/yr), so a monthly refresh is generous.
tickermap:
  snapshot_path: data/ticker_articles.json
  overrides_path: radar/ticker_overrides.yml
  max_age_days: 30
```

- [ ] **Step 2: Extend the hermeticity guard FIRST**

In `tests/conftest.py`, add to the existing `_no_live_quotes_or_summaries` fixture:

```python
    import radar.tickermap
    monkeypatch.setattr(radar.tickermap, "_get_json", lambda *a, **k: None)
```

Do this before wiring `run.py`, or the next full-suite run makes live SPARQL calls.

- [ ] **Step 3: Write the failing test**

In `tests/test_run_smoke.py`:

```python
def test_run_maps_titles_and_reports_the_source(monkeypatch, tmp_path):
    """The map reaches about.describe, and the source reports itself like every other."""
    import radar.run as run
    seen = {}
    monkeypatch.setattr(run.tickermap, "fetch_ticker_map",
                        lambda cfg, run_day: {"AAPL": "Apple Inc."})
    monkeypatch.setattr(run.about, "fetch_summary",
                        lambda title, ua="x": seen.setdefault("title", title) or {"desc": "d", "extract": "e"})
    # ... existing smoke-test stubs for mentions/tradestie/shorts/news/option_stats ...
    out = tmp_path / "out"
    run.main(["--dry-run", "--no-email", "--out", str(out)])
    health = json.loads((out / "health.json").read_text())
    assert "tickermap" in health["sources"]
```

Match the surrounding stubs in that file exactly — copy them from `test_dry_run_writes_signals_and_weights`.

- [ ] **Step 4: Wire `run.py`**

Add the import beside the other `radar` imports:

```python
from radar import tickermap
```

In `main`, before the enrich loop at `run.py:76`:

```python
    ticker_titles = tickermap.fetch_ticker_map(cfg, run_day)
```

Change `_enrich_ticker`'s signature to accept `titles` and pass the looked-up title through:

```python
def _enrich_ticker(s, by_ticker, about_cache, about_ua, themes, titles):
    a = by_ticker.get(s.ticker)
    ...
    s.about = about.describe(s.ticker, a.name, titles.get(s.ticker), about_cache, about_ua)
```

Update both call sites (`run.py:79` and `:81`) to pass `ticker_titles`.

In the `sources` dict at `run.py:163-171`, add:

```python
        "tickermap": "ok" if ticker_titles else "down",
```

- [ ] **Step 5: Run the full suite**

Run: `source .venv/bin/activate && python -m pytest -q`
Expected: PASS, all tests.

- [ ] **Step 6: Verify hermeticity**

Run under the socket blocker. Expected: 0 DNS lookups.

- [ ] **Step 7: Add the footer LED**

`radar/templates/dashboard.html.j2` renders `health.sources` in a generic loop (around `:394`), so no template change should be needed. **Verify this by rendering** — do not assume. If the loop is generic, say so in the commit; if it is not, add the entry.

- [ ] **Step 8: Commit**

```bash
git add radar/run.py config.yaml tests/conftest.py tests/test_run_smoke.py
git commit -m "feat(tickermap): wire the map into the run

Every source fails soft and reports itself: tickermap gets a health.json
sources entry and a footer LED like the other eight."
```

---

## Self-Review Notes

- Spec §2.4's truncation guard is Task 2 Step 1 test 1 — the highest-value test in the plan.
- Spec §2.6's anti-fuzzy guarantee is Task 4's call-count assertion, not a return-value check.
- Spec §2.8's cache migration is Task 4, tested in both directions (stale schema and no schema).
- Spec §2.3's "sole ended statement survives" proviso is Task 1's `BBBY` test — the rule that preserves all 251 resolutions.
- Spec §2.7's staleness check is in Task 2 (`_snapshot_age_days`), tested in all three directions: fresh skips the fetch, stale refreshes, unparseable date fails toward refreshing. Caught during self-review — it had been deferred, which would have left every daily run paying a ~22s query for data that changes <1%/yr.
- `from datetime import date` must be added to `radar/tickermap.py`'s imports for `_snapshot_age_days`.
