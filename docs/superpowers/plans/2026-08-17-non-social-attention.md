# E2 — Non-Social Attention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two non-Reddit attention sources — Wikimedia pageviews as a daily published component, and FINRA short interest as an `as_of`-stamped context field that never enters the composite.

**Architecture:** `radar/pageviews.py` fetches a 35-day window per mapped ticker in one request and scores a self-relative spike (today vs. the ticker's own 28-day median, log2-scaled). `radar/short_interest.py` pulls FINRA's consolidated file, filters the `999.99` sentinel, and vendors a snapshot refreshed only when the settlement date advances. `attention` joins `components_for`'s dict **with no weight entry**, so it publishes in `data.json` and is excluded from the blend.

**Tech Stack:** Python 3.12, `requests`, pytest with `monkeypatch`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-17-non-social-attention-design.md`

**Depends on:** `docs/superpowers/plans/2026-08-17-ticker-article-mapping.md` (E2a) must land first — pageviews are fetched per exact article title, and E2a is what produces titles.

## Global Constraints

- **The suite is hermetic and must stay that way.** No test opens a socket. Every new fetcher gets a stub in `tests/conftest.py`'s autouse guard **before** it is wired into `run.py`.
- **House stubbing style is `monkeypatch.setattr(module, "_private_helper", lambda ...)`.** No `unittest.mock`.
- **Every source fails soft and reports itself** in `health.json`'s `sources` block plus a footer LED.
- **`attention` must never appear in `config.yaml`'s `composite.weights`.** That absence is the mechanism, not an oversight — `composite.py:55` filters on `weights.get(k, 0) > 0`.
- **Short interest is never a composite component**, weighted or otherwise. It does not go in `components_for`.
- **Wikimedia requires a non-empty User-Agent** (empty → HTTP 403) and **`agent=user`**, not `all-agents` (measured 32% bot inflation).
- Run tests with `source .venv/bin/activate && python -m pytest -q`.

---

### Task 1: Spike scoring — pure math

**Files:**
- Create: `radar/pageviews.py`
- Create: `tests/test_pageviews.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `spike_score(series: list[int], min_baseline: int = 10, min_days: int = 21) -> float | None` — takes a chronological list of daily views ending at D-1, returns 0–100 or `None`.

Scoring, from spec §2.2: `current` = last element; `baseline` = median of the 28 preceding; `attention = 50 + 25 * clamp(log2(current/baseline), -2, +2)`.

- [ ] **Step 1: Write the failing tests**

```python
import math
import radar.pageviews as pv


def _flat(n, value):
    return [value] * n


def test_ratio_one_is_fifty():
    assert pv.spike_score(_flat(29, 100)) == 50.0


def test_anchors():
    """Anchors verified against the spec: 2x -> 75, 4x -> 100, 0.25x -> 0."""
    assert pv.spike_score(_flat(28, 100) + [200]) == 75.0
    assert pv.spike_score(_flat(28, 100) + [400]) == 100.0
    assert pv.spike_score(_flat(28, 100) + [25]) == 0.0


def test_clamps_beyond_two_log_units():
    assert pv.spike_score(_flat(28, 100) + [800]) == 100.0
    assert pv.spike_score(_flat(28, 100) + [10]) == 0.0


def test_uses_median_not_mean():
    """A single prior spike must not suppress today's score. Mean of this baseline is
    ~132, median is 100 -- with a mean the score would be visibly lower."""
    baseline = _flat(27, 100) + [1000]
    assert pv.spike_score(baseline + [200]) == 75.0


def test_none_when_baseline_too_thin():
    """A near-zero baseline makes the ratio explode: 2 views -> 12 would score 100.
    A name with no meaningful Wikipedia traffic has no attention signal."""
    assert pv.spike_score(_flat(28, 5) + [50]) is None


def test_none_when_too_few_days():
    assert pv.spike_score(_flat(15, 100) + [200]) is None


def test_none_on_empty_or_junk():
    for junk in ([], None, [100]):
        assert pv.spike_score(junk) is None


def test_live_probe_regression():
    """Measured 2026-08-17: TSLA current 2554 against a 2816.5 median -> 46.47."""
    series = _flat(14, 2816) + _flat(14, 2817) + [2554]
    assert pv.spike_score(series) == 46.47
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_pageviews.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'radar.pageviews'`

- [ ] **Step 3: Write the implementation**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add radar/pageviews.py tests/test_pageviews.py
git commit -m "feat(pageviews): self-relative spike scoring

Today vs the ticker's own 28d median, log2-scaled and clamped. Median not
mean, so a single prior spike does not suppress today. None below a 10
views/day baseline -- on thin traffic the ratio explodes and 2 -> 12 views
would score 100."
```

---

### Task 2: Pageviews fetch

**Files:**
- Modify: `radar/pageviews.py`
- Modify: `tests/test_pageviews.py`
- Create: `tests/fixtures/pageviews_tsla.json`

**Interfaces:**
- Consumes: `spike_score` from Task 1; `titles: dict[str, str]` from `tickermap.fetch_ticker_map`.
- Produces: `fetch_attention(titles: dict[str, str], tickers: list[str], run_day: str, sleep_s: float = 0.2) -> tuple[dict[str, float], dict[str, int]]` — returns `({ticker: attention 0-100}, {ticker: latest daily views})`. Fail-soft; a ticker that errors is simply absent.
- Also produces `_get_series(title: str, start: str, end: str) -> list[int] | None` — the private transport and stub seam.

- [ ] **Step 1: Write the fixture**

`tests/fixtures/pageviews_tsla.json` — a real-shaped response with 29 items:

```json
{"items": [
  {"project": "en.wikipedia", "article": "Tesla,_Inc.", "granularity": "daily",
   "timestamp": "2026071900", "access": "all-access", "agent": "user", "views": 2816}
]}
```

Generate the remaining 28 items programmatically in the test rather than pasting them.

- [ ] **Step 2: Write the failing tests**

```python
def test_unmapped_ticker_makes_no_request(monkeypatch):
    """The E2a anti-fuzzy guarantee holding at the E2 boundary. Assert the CALL COUNT:
    a missing entry could otherwise mean 'fetched and failed', which is different."""
    calls = []
    monkeypatch.setattr(pv, "_get_series", lambda *a, **k: calls.append(a))
    scores, raw = pv.fetch_attention({}, ["MVIS"], "2026-08-17")
    assert calls == []
    assert scores == {} and raw == {}


def test_maps_ticker_through_the_exact_title(monkeypatch):
    seen = {}
    def fake(title, start, end):
        seen["title"] = title
        return [100] * 28 + [200]
    monkeypatch.setattr(pv, "_get_series", fake)
    scores, raw = pv.fetch_attention({"TSLA": "Tesla, Inc."}, ["TSLA"], "2026-08-17")
    assert seen["title"] == "Tesla, Inc."
    assert scores["TSLA"] == 75.0
    assert raw["TSLA"] == 200


def test_one_ticker_failing_does_not_take_down_the_rest(monkeypatch):
    def fake(title, start, end):
        return None if title == "Bad" else [100] * 28 + [200]
    monkeypatch.setattr(pv, "_get_series", fake)
    scores, _ = pv.fetch_attention({"A": "Bad", "B": "Good"}, ["A", "B"], "2026-08-17")
    assert "A" not in scores and scores["B"] == 75.0


def test_thin_baseline_is_absent_not_zero(monkeypatch):
    """None from spike_score must not become 0.0 -- a real zero says 'collapsed
    attention', absence says 'no signal'. composite.py renormalizes around absence."""
    monkeypatch.setattr(pv, "_get_series", lambda *a, **k: [2] * 28 + [12])
    scores, raw = pv.fetch_attention({"T": "Title"}, ["T"], "2026-08-17")
    assert "T" not in scores
    assert raw["T"] == 12, "raw views still published even when unscored"


def test_parse_series_reads_views_in_order():
    raw = {"items": [{"timestamp": "2026081400", "views": 10},
                     {"timestamp": "2026081500", "views": 20},
                     {"timestamp": "2026081600", "views": 30}]}
    assert pv.parse_series(raw) == [10, 20, 30]


def test_parse_series_never_raises():
    for junk in (None, {}, {"items": "nope"}, {"items": [{"views": "x"}]}):
        assert pv.parse_series(junk) == []
```

- [ ] **Step 3: Run tests to verify they fail**

Expected: FAIL — `AttributeError: module 'radar.pageviews' has no attribute 'fetch_attention'`

- [ ] **Step 4: Write the implementation**

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add radar/pageviews.py tests/test_pageviews.py tests/fixtures/pageviews_tsla.json
git commit -m "feat(pageviews): fetch a 35d window per mapped ticker

One request returns the whole range, so there is no warm-up period. An
unmapped ticker makes no request at all -- asserted on call count, since
a wrong article yields a plausible but entirely fictitious series."
```

---

### Task 3: FINRA short interest

**Files:**
- Create: `radar/short_interest.py`
- Create: `tests/test_short_interest.py`
- Create: `tests/fixtures/finra_short_interest.json`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `parse_rows(raw) -> tuple[dict[str, dict], str]` — `({TICKER: {"days_to_cover": float, "shares": int}}, settlement_date)`. Pure.
  - `fetch_short_interest(cfg, run_day: str) -> tuple[dict[str, dict], str]` — fail-soft, vendored.
  - `_post_json(url, payload, ua, ...) -> list | None` — private transport, stub seam.

**Two traps this task exists to avoid**, both measured:
1. `daysToCoverQuantity == 999.99` is a **sentinel** for zero average daily volume (e.g. `AAALF`, ADV 0), not a real 999-day cover. Unfiltered it dominates any sort.
2. FINRA caps responses at **5,000 rows**. A full pull is 5 paginated calls.

- [ ] **Step 1: Write the fixture**

`tests/fixtures/finra_short_interest.json`:

```json
[{"symbolCode": "NVDA", "daysToCoverQuantity": 2.47, "averageDailyVolumeQuantity": 131174356,
  "currentShortPositionQuantity": 324052767, "settlementDate": "2026-07-31", "marketClassCode": "NNM"},
 {"symbolCode": "MVIS", "daysToCoverQuantity": 6.73, "averageDailyVolumeQuantity": 8841668,
  "currentShortPositionQuantity": 59527128, "settlementDate": "2026-07-31", "marketClassCode": "NNM"},
 {"symbolCode": "AAALF", "daysToCoverQuantity": 999.99, "averageDailyVolumeQuantity": 0,
  "currentShortPositionQuantity": 1000, "settlementDate": "2026-07-31", "marketClassCode": "OTC"}]
```

- [ ] **Step 2: Write the failing tests**

```python
import json
from pathlib import Path
import radar.short_interest as si

RAW = json.loads(Path("tests/fixtures/finra_short_interest.json").read_text())


def test_parses_days_to_cover_and_shares():
    rows, settlement = si.parse_rows(RAW)
    assert rows["NVDA"]["days_to_cover"] == 2.47
    assert rows["NVDA"]["shares"] == 324052767
    assert settlement == "2026-07-31"


def test_sentinel_days_to_cover_is_filtered():
    """999.99 means zero average volume, not a 999-day cover. Unfiltered it tops
    every ranking."""
    rows, _ = si.parse_rows(RAW)
    assert "AAALF" not in rows


def test_parse_rows_never_raises():
    for junk in (None, {}, "nope", [{"symbolCode": None}], [{"bad": 1}]):
        rows, settlement = si.parse_rows(junk)
        assert rows == {} and settlement == ""


def test_refreshes_only_when_settlement_advances(monkeypatch, tmp_path):
    """Twice-monthly data. Re-pulling 22k rows daily is waste."""
    snap = tmp_path / "short_interest.json"
    snap.write_text(json.dumps({"schema": 1, "settlement": "2026-07-31",
                                "rows": {"NVDA": {"days_to_cover": 2.47, "shares": 1}}}))
    calls = []
    monkeypatch.setattr(si, "_post_json", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: "2026-07-31")
    rows, settlement = si.fetch_short_interest(_cfg(tmp_path), "2026-08-17")
    assert calls == [], "same settlement date must not trigger a full pull"
    assert rows["NVDA"]["days_to_cover"] == 2.47 and settlement == "2026-07-31"


def test_upstream_down_serves_snapshot_and_warns(monkeypatch, tmp_path):
    snap = tmp_path / "short_interest.json"
    snap.write_text(json.dumps({"schema": 1, "settlement": "2026-07-15",
                                "rows": {"NVDA": {"days_to_cover": 3.0, "shares": 1}}}))
    monkeypatch.setattr(si, "_post_json", lambda *a, **k: None)
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: None)
    rows, settlement = si.fetch_short_interest(_cfg(tmp_path), "2026-08-17")
    assert rows["NVDA"]["days_to_cover"] == 3.0
    assert settlement == "2026-07-15"
    assert any("snapshot" in str(e).lower() for e in degrade.events())


def test_both_gone_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(si, "_post_json", lambda *a, **k: None)
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: None)
    assert si.fetch_short_interest(_cfg(tmp_path), "2026-08-17") == ({}, "")


def test_pagination_walks_until_short_page(monkeypatch, tmp_path):
    """5,000-row cap: a full page means there is more to fetch."""
    pages = [[dict(RAW[0], symbolCode=f"T{i}") for i in range(5000)],
             [dict(RAW[0], symbolCode="LAST")]]
    monkeypatch.setattr(si, "_post_json", lambda *a, **k: pages.pop(0) if pages else [])
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: "2026-08-14")
    rows, _ = si.fetch_short_interest(_cfg(tmp_path), "2026-08-17")
    assert "LAST" in rows, "must keep paging past a full 5000-row page"
```

Add a `_cfg` helper mirroring the one in `tests/test_tickermap.py`, with
`short_interest=SimpleNamespace(snapshot_path=..., page_size=5000)`.

- [ ] **Step 3: Run tests to verify they fail**

Expected: FAIL — module does not exist.

- [ ] **Step 4: Write the implementation**

Follow `radar/cramer.py`'s structure exactly: module docstring stating source and
failure philosophy, private `_post_json` with the same retry shape, a pure `parse_rows`,
and a fail-soft public `fetch_short_interest` with the vendor/snapshot ladder. Key
details:

```python
URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
SENTINEL_DTC = 999.99      # zero average daily volume, not a real 999-day cover
PAGE = 5000                # FINRA's hard cap per request
```

`_latest_settlement(ua)` requests one row sorted by settlement date descending and
returns its `settlementDate`, or `None`. `fetch_short_interest` compares it to the
snapshot's `settlement`; if unchanged, it returns the snapshot without paging.

- [ ] **Step 5: Run tests to verify they pass**

- [ ] **Step 6: Commit**

```bash
git add radar/short_interest.py tests/test_short_interest.py tests/fixtures/finra_short_interest.json
git commit -m "feat(short-interest): FINRA consolidated pull, vendored

FINRA over Nasdaq: identical data (verified on MVIS), keyless, batchable,
no bot posture -- Nasdaq returned HTTP 000 on a default curl UA. Filters
the 999.99 days-to-cover sentinel and pages past the 5000-row cap."
```

---

### Task 4: `attention` as a published, unweighted component

**Files:**
- Modify: `radar/composite.py:9-14` (docstring), `:36-48` (`components_for`)
- Modify: `radar/models.py` (add `attention` and short-interest fields to `Signal`)
- Modify: `tests/test_composite.py`

**Interfaces:**
- Consumes: `s.attention` on the `Signal` dataclass, set by the run.
- Produces: an `attention` key in `components_for`'s returned dict.

**This task's central claim needs a test, not a comment.** `attention` is excluded from the blend only because `config.yaml` has no weight for it and `composite.py:55` filters on `weights.get(k, 0) > 0`. That is an easily-broken invariant.

- [ ] **Step 1: Write the failing tests**

```python
def test_attention_is_published_in_components():
    s = _sig(attention=88.0)
    assert composite.components_for(s, [s], None, {})["attention"] == 88.0


def test_attention_is_none_when_unscored():
    assert composite.components_for(_sig(attention=None), [_sig()], None, {})["attention"] is None


def test_attention_does_not_change_the_composite():
    """The central claim of spec 2.3. attention ships with no weight, so the blended
    number must be byte-identical with and without it. If someone adds a weight for
    it, this test fails and the regime-boundary conversation happens BEFORE the
    backtest series is silently broken."""
    weights = dict(composite.DEFAULT_WEIGHTS)
    without = {"velocity": 70.0, "direction": 60.0}
    with_att = dict(without, attention=100.0)
    assert composite.blend(with_att, weights) == composite.blend(without, weights)


def test_default_weights_has_exactly_seven_keys():
    """attention must NOT be here. Its absence is the mechanism."""
    assert len(composite.DEFAULT_WEIGHTS) == 7
    assert "attention" not in composite.DEFAULT_WEIGHTS
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement**

Add to `radar/models.py`'s `Signal`, beside `short_ratio`:

```python
    attention: float | None = None          # Wikimedia pageview spike, 0-100
    pageviews: int | None = None            # raw daily views, context only
    days_to_cover: float | None = None      # FINRA short interest, context only
    short_interest_shares: int | None = None
    short_interest_as_of: str | None = None # settlement date -- render it ALWAYS
```

Add one line to `components_for`'s dict, after `"events"`:

```python
        "attention": (float(s.attention) if s.attention is not None else None),
```

Update the docstring's component-semantics paragraph to describe `attention`, and
**correct the false claim in the same docstring** (lines 4-6). Replace:

> `recalibrated from measured ICs once backtest.json's power block turns sufficient (a config change, not a code change)`

with:

> `intended to be recalibrated from measured ICs once backtest.json's power block turns sufficient. NOTE: per-component ICs are not computed anywhere yet — backtest.py's _frames() emits the raw velocity score — so changing a weight's number is config-only, but producing the measurement that justifies it is unbuilt work. See the E2 spec's follow-up.`

Add a line noting `attention` is published but carries no weight, and why.

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Commit**

```bash
git add radar/composite.py radar/models.py tests/test_composite.py
git commit -m "feat(composite): publish attention, deliberately unweighted

composite.py:55 filters on weights.get(k,0) > 0, so a component with no
weight publishes in data.json and is dropped from the blend: no rebalance
of the existing seven, and the composite value is unchanged, so this is
not a regime boundary. Pinned with a test rather than left as an emergent
property of a filter expression.

Also corrects the docstring's 'a config change, not a code change' claim.
Per-component ICs are computed nowhere -- _frames() emits the raw velocity
score -- so the measurement that would justify a reweight does not exist."
```

---

### Task 5: Wire both sources into the run

**Files:**
- Modify: `radar/run.py`, `config.yaml`, `tests/conftest.py`
- Modify: `radar/templates/dashboard.html.j2`
- Modify: `tests/test_run_smoke.py`

- [ ] **Step 1: Extend the hermeticity guard FIRST**

In `tests/conftest.py`'s autouse fixture:

```python
    import radar.pageviews
    import radar.short_interest
    monkeypatch.setattr(radar.pageviews, "_get_series", lambda *a, **k: None)
    monkeypatch.setattr(radar.short_interest, "_post_json", lambda *a, **k: None)
    monkeypatch.setattr(radar.short_interest, "_latest_settlement", lambda *a, **k: None)
```

Do this before wiring, or the next full-suite run makes live calls.

- [ ] **Step 2: Add config blocks**

```yaml
# Wikimedia pageviews. agent=user, not all-agents: measured 32% bot inflation on NVDA
# (3,765 user vs 5,501 all-agents), and bot traffic is not attention.
pageviews:
  sleep_seconds: 0.2
  min_baseline_views: 10

# FINRA consolidated short interest. Twice-monthly, settlement-based, 9-12 days behind
# the settlement date -- CONTEXT, never a daily composite component.
short_interest:
  snapshot_path: data/short_interest.json
  page_size: 5000
```

**Do not add `attention` to `composite.weights`.**

- [ ] **Step 3: Write the failing test**

```python
def test_attention_ships_in_components_and_weights_stay_seven(monkeypatch, tmp_path):
    # ... standard smoke-test stubs, plus:
    monkeypatch.setattr(run.pageviews, "fetch_attention",
                        lambda titles, tickers, run_day, **k: ({"AAPL": 88.0}, {"AAPL": 5000}))
    out = tmp_path / "out"
    run.main(["--dry-run", "--no-email", "--out", str(out)])
    data = json.loads((out / "data.json").read_text())
    row = next(s for s in data["signals"] if s["ticker"] == "AAPL")
    assert row["components"]["attention"] == 88.0
    assert "attention" not in data["weights"]
    assert abs(sum(data["weights"].values()) - 1.0) < 1e-6
```

- [ ] **Step 4: Wire `run.py`**

After the ticker map is fetched (E2a, Task 5), and after the board is built:

```python
    attention, raw_views = pageviews.fetch_attention(
        ticker_titles, [s.ticker for s in board], run_day)
    si_rows, si_as_of = short_interest.fetch_short_interest(cfg, run_day)
    for s in board:
        s.attention = attention.get(s.ticker)
        s.pageviews = raw_views.get(s.ticker)
        row = si_rows.get(s.ticker) or {}
        s.days_to_cover = row.get("days_to_cover")
        s.short_interest_shares = row.get("shares")
        s.short_interest_as_of = si_as_of or None
        history.annotate(run_day, s.ticker, attention=s.attention, pageviews=s.pageviews)
```

Add to the `sources` dict:

```python
        "wikimedia": "ok" if attention else "down",
        "finra_si": "ok" if si_rows else "down",
```

Add `days_to_cover`, `short_interest_as_of` and `pageviews` to the `signals` payload
rows and to `_detail_blob`.

- [ ] **Step 5: Render `as_of` — non-negotiable**

In `dashboard.html.j2`'s detail modal, render short interest **only** with its
settlement date attached, e.g. `days to cover 6.7 (as of 2026-07-31)`. At 11–24 days
stale, sitting next to `short vol` — a genuinely D-1 number — a bare figure implies a
freshness it does not have. Add `attention` to the `_COMP_ORDER` list in `run.py` and
the mirrored `CO` array in the template's JavaScript.

- [ ] **Step 6: Run the full suite and verify hermeticity**

Run: `source .venv/bin/activate && python -m pytest -q`, then again under the socket
blocker. Expected: all pass, 0 DNS lookups.

- [ ] **Step 7: Commit**

```bash
git add radar/run.py config.yaml tests/conftest.py tests/test_run_smoke.py radar/templates/dashboard.html.j2
git commit -m "feat(e2): wire pageviews and short interest into the run

Both sources report themselves in health.json. attention ships in
components with no weight; short interest ships as context with its
settlement date rendered everywhere it appears."
```

---

## Self-Review Notes

- Spec §2.2's three `None` conditions are Task 1 tests 5–7, each asserted separately.
- Spec §2.3's "composite unchanged" claim is Task 4 test 3 — the test that turns an invariant resting on a filter expression into something that fails loudly.
- Spec §2.6's anti-fuzzy guarantee is re-asserted at the E2 boundary in Task 2 test 1, on call count.
- Spec §3.2's 5,000-row cap and `999.99` sentinel are Task 3 tests 2 and 7.
- Spec §3.3's `as_of` requirement is Task 5 Step 5.
- **Ordering note:** Task 5 depends on E2a Task 5 having landed, because `ticker_titles` is produced there. Tasks 1–4 have no such dependency and can be built in parallel with E2a.
