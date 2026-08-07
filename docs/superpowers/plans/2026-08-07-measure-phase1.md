# Measure & Widen — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the radar grade itself — an append-only Early Plays log, a weekly backtest of the velocity signal published as `backtest.json`, a daily picks scorecard, and Tradestie directional-sentiment ingestion — per `docs/superpowers/specs/2026-08-07-measure-and-widen-design.md` (Phase 1).

**Architecture:** Three new modules (`radar/plays_log.py`, `radar/tradestie.py`, `radar/backtest.py`) plus small wire-ins to `radar/run.py`, `radar/history.py`, `radar/health.py`, the dashboard template, and workflows. The backtest runs weekly in its own workflow and commits `data/backtest.json` to the orphan `data` branch; the daily run copies it into `out/` so it publishes on Pages. All fetchers are fail-soft via `radar.degrade.warn` — nothing here may ever crash or block the daily board.

**Tech Stack:** Python 3.11, pytest 8.3.4, requests 2.32.3, yfinance 1.5.2 (exact-pinned), jinja2. **No new dependencies** — Spearman/Newey-West are implemented by hand with `statistics`/`math`.

## Global Constraints

- Python floor **3.11**; every new module starts with `from __future__ import annotations`.
- **No new pip dependencies** (requirements.txt is pinned; scipy/pandas/numpy are NOT available).
- Every network fetch: fail-soft, `degrade.warn("<source>", exc)` breadcrumb, never raises out.
- Bot state lives on the orphan **`data` branch** (`data/history.json` pattern); new state files (`data/plays_log.json`, `data/backtest.json`) must be added to BOTH workflows' commit-back `cp` lines.
- **Look-ahead rule (spec):** a signal recorded on day *t* may only be priced from the first trading day strictly **after** *t* — never day-*t* close.
- History schema: `{ticker: {YYYY-MM-DD: {weighted, raw, authors, pct_bull, score, state}}}`; `History.baseline()` requires `weighted` to exist in every day-record — never create a day-record without it.
- Regime note (fixed constant): `2026-08-07` — PR #4 merged; `state` in history is board-relative for board names from this date.
- Run tests with `python -m pytest -q` (CI) — locally `uv run --with-requirements requirements.txt -- python -m pytest -q` if pytest isn't installed.
- Commit after every task; suite must be green at every commit.

---

## File Structure

**Create:**
- `radar/plays_log.py` — append-only Early Plays pick log (data-branch state)
- `radar/tradestie.py` — Tradestie WSB sentiment fetch/parse
- `radar/backtest.py` — backtest computations + CLI (`python -m radar.backtest`)
- `.github/workflows/backtest.yml` — weekly backtest job
- `tests/test_plays_log.py`, `tests/test_tradestie.py`, `tests/test_backtest.py`
- `tests/fixtures/tradestie.json` — recorded live API response

**Modify:**
- `radar/history.py` — add `History.annotate()`
- `radar/health.py` — add `sources` block to `assess()`
- `radar/run.py` — wire plays log, tradestie, sources, scorecard
- `radar/templates/dashboard.html.j2` — scorecard card (after the `plays` block, ~line 203)
- `config.yaml` — `tradestie:` block
- `.github/workflows/daily.yml` — commit-back additions + backtest.json copy
- `tests/test_health.py` — sources-block cases

---

### Task 1: Early Plays log (`radar/plays_log.py`)

**Files:**
- Create: `radar/plays_log.py`, `tests/test_plays_log.py`
- Modify: `radar/run.py` (after `early_plays = _early_plays(board)`, line ~72), `.github/workflows/daily.yml` (cp line 56)

**Interfaces:**
- Consumes: `_early_plays(board)` output — `list[dict]` with keys `ticker, thesis, risk, conviction, name, vel24`.
- Produces: `append_picks(path, run_day: str, picks: list[dict], board_by_ticker: dict) -> int` (returns number of NEW entries written; used by run.py and Task 6 reads the file). On-disk schema:
  `{"picks": [{"date","ticker","thesis","risk","conviction","mentions","vel","state"}]}` — append-only, deduped on `(date, ticker)`, sorted by `(date, ticker)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_plays_log.py
import json
from pathlib import Path
from radar.plays_log import append_picks, load_picks
from radar.models import Signal

def _sig(t):
    return Signal(ticker=t, mentions=42, state="hot", vel_24h=3.2)

def test_append_creates_file_and_dedupes(tmp_path):
    p = tmp_path / "plays_log.json"
    picks = [{"ticker": "AAA", "thesis": "t", "risk": "r", "conviction": "high"}]
    by = {"AAA": _sig("AAA")}
    assert append_picks(p, "2026-08-08", picks, by) == 1
    assert append_picks(p, "2026-08-08", picks, by) == 0          # same day+ticker -> no dup
    data = json.loads(p.read_text())
    assert len(data["picks"]) == 1
    row = data["picks"][0]
    assert row["date"] == "2026-08-08" and row["ticker"] == "AAA"
    assert row["mentions"] == 42 and row["state"] == "hot" and row["vel"] == 3.2

def test_append_next_day_appends(tmp_path):
    p = tmp_path / "plays_log.json"
    picks = [{"ticker": "AAA", "thesis": "t", "risk": "r", "conviction": "low"}]
    append_picks(p, "2026-08-08", picks, {})
    assert append_picks(p, "2026-08-09", picks, {}) == 1
    assert len(load_picks(p)) == 2

def test_load_tolerates_missing_and_corrupt(tmp_path):
    assert load_picks(tmp_path / "nope.json") == []
    bad = tmp_path / "bad.json"; bad.write_text("{not json")
    assert load_picks(bad) == []

def test_corrupt_file_does_not_lose_new_picks(tmp_path):
    bad = tmp_path / "plays_log.json"; bad.write_text("{not json")
    picks = [{"ticker": "BBB", "thesis": "t", "risk": "", "conviction": ""}]
    assert append_picks(bad, "2026-08-08", picks, {}) == 1        # corrupt -> start fresh
    assert [r["ticker"] for r in load_picks(bad)] == ["BBB"]
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_plays_log.py -q` → FAIL (`No module named 'radar.plays_log'`).

- [ ] **Step 3: Implement**

```python
# radar/plays_log.py
"""Append-only log of Early Plays picks — the radar's track record (data-branch state).

Each daily run appends that day's recommend_buys output; nothing is ever rewritten,
so the scorecard/backtest can grade every pick the radar ever made. Dedupe key is
(date, ticker). Corrupt/missing files start fresh rather than crash (fail-soft, but
append_picks may raise on write errors — the caller wraps it in degrade.warn)."""
from __future__ import annotations

import json
from pathlib import Path


def load_picks(path) -> list[dict]:
    """The full pick log, oldest first. [] on missing/corrupt file."""
    p = Path(path)
    try:
        data = json.loads(p.read_text())
        picks = data.get("picks", [])
        return picks if isinstance(picks, list) else []
    except (OSError, ValueError):
        return []


def append_picks(path, run_day: str, picks: list[dict], board_by_ticker: dict) -> int:
    """Append today's picks (deduped on (date, ticker)); returns how many were new.
    `board_by_ticker` maps ticker -> Signal so each entry snapshots the board metrics
    that justified the pick (mentions / vel_24h / state)."""
    existing = load_picks(path)
    seen = {(r.get("date"), r.get("ticker")) for r in existing}
    added = 0
    for pk in picks:
        t = str(pk.get("ticker") or "").upper()
        if not t or (run_day, t) in seen:
            continue
        s = board_by_ticker.get(t)
        existing.append({
            "date": run_day, "ticker": t,
            "thesis": str(pk.get("thesis") or ""), "risk": str(pk.get("risk") or ""),
            "conviction": str(pk.get("conviction") or ""),
            "mentions": getattr(s, "mentions", 0) if s else 0,
            "vel": getattr(s, "vel_24h", None) if s else None,
            "state": getattr(s, "state", "") if s else ""})
        seen.add((run_day, t)); added += 1
    existing.sort(key=lambda r: (r.get("date", ""), r.get("ticker", "")))
    Path(path).write_text(json.dumps({"picks": existing}, indent=0))
    return added
```

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_plays_log.py -q` → 4 passed.

- [ ] **Step 5: Wire into run.py.** In `radar/run.py` add import `from radar.plays_log import append_picks`, then directly under `early_plays = _early_plays(board)` (before the `if not args.dry_run:` about-cache save):

```python
    if early_plays and not args.dry_run:
        try:                                            # log the call — the track record
            append_picks("data/plays_log.json", run_day, early_plays,
                         {s.ticker: s for s in board})
        except Exception as e:
            degrade.warn("plays-log append", e)
```

- [ ] **Step 6: Persist to the data branch.** In `.github/workflows/daily.yml`, extend the commit-back copy (line 56) to:

```yaml
          cp -f data/history.json data/about.json data/plays_log.json /tmp/state/data/ 2>/dev/null || true
```

- [ ] **Step 7: Full suite green** — `python -m pytest -q` → all pass (209 + 4 new).

- [ ] **Step 8: Commit**

```bash
git add radar/plays_log.py tests/test_plays_log.py radar/run.py .github/workflows/daily.yml
git commit -m "feat(measure): append-only Early Plays log on the data branch"
```

---

### Task 2: Tradestie directional sentiment (`radar/tradestie.py`)

**Files:**
- Create: `radar/tradestie.py`, `tests/test_tradestie.py`, `tests/fixtures/tradestie.json`
- Modify: `radar/history.py` (add `annotate`), `radar/run.py`, `config.yaml`

**Interfaces:**
- Consumes: `cfg.tradestie` (SimpleNamespace from config.yaml), `radar.degrade.warn`.
- Produces:
  - `TsRow` dataclass: `ticker: str, sentiment: str, score: float, comments: int`
  - `parse_feed(raw) -> list[TsRow]` (pure, never raises)
  - `fetch_wsb(cfg) -> list[TsRow]` (network, fail-soft → `[]`)
  - `to_aggregates(rows) -> list[Aggregate]` (fallback board input; `radar.apewisdom.Aggregate`)
  - `bull_pct(score: float) -> float` (score −1..1 → 0..100, clamped)
  - `History.annotate(day: str, ticker: str, **fields) -> bool` (merges keys into an EXISTING day-record only; returns False if absent)

- [ ] **Step 1: Record the live fixture.** Run:

```bash
curl -s "https://api.tradestie.com/v1/apps/reddit" -H "User-Agent: reddit-signal-radar/0.1" | python3 -m json.tool | head -30
curl -s "https://api.tradestie.com/v1/apps/reddit" -H "User-Agent: reddit-signal-radar/0.1" > tests/fixtures/tradestie.json
```

Inspect the head output: expected shape is a JSON **list** of objects with keys `no_of_comments`, `sentiment` ("Bullish"/"Bearish"), `sentiment_score` (float), `ticker`. **If the shape differs, adjust `parse_feed` and the fixture test to what you actually recorded — the fixture is ground truth.** Confirm `sentiment_score` values sit in −1..1 (VADER-style compound); if you observe values outside that range, change `bull_pct` clamping accordingly and note it in the module docstring.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_tradestie.py
import json, pathlib
from radar.tradestie import parse_feed, fetch_wsb, to_aggregates, bull_pct, TsRow
from radar.history import History

def test_parse_feed_from_live_fixture():
    raw = json.loads(pathlib.Path("tests/fixtures/tradestie.json").read_text())
    rows = parse_feed(raw)
    assert len(rows) >= 10                                  # top-50 feed
    r = rows[0]
    assert r.ticker and r.sentiment in ("Bullish", "Bearish")
    assert isinstance(r.score, float) and isinstance(r.comments, int)

def test_parse_feed_never_raises_on_garbage():
    for raw in [None, {}, [], "x", [{"ticker": None}], [{"no_of_comments": "x"}], ["garbage"]]:
        assert isinstance(parse_feed(raw), list)

def test_bull_pct_maps_and_clamps():
    assert bull_pct(0.0) == 50.0
    assert bull_pct(1.0) == 100.0 and bull_pct(-1.0) == 0.0
    assert bull_pct(9.9) == 100.0 and bull_pct(-9.9) == 0.0  # out-of-range clamps

def test_to_aggregates_fallback_shape():
    rows = [TsRow(ticker="GME", sentiment="Bullish", score=0.2, comments=150)]
    aggs = to_aggregates(rows)
    assert aggs[0].ticker == "GME" and aggs[0].mentions == 150
    assert aggs[0].subreddit == "wallstreetbets" and aggs[0].mentions_24h_ago == 0

def test_fetch_wsb_fail_soft(monkeypatch):
    import radar.tradestie as ts
    monkeypatch.setattr(ts, "_get", lambda *a, **k: None)
    from types import SimpleNamespace
    cfg = SimpleNamespace(tradestie=SimpleNamespace(url="http://x", user_agent="t", max_retries=1, sleep_seconds=0))
    assert ts.fetch_wsb(cfg) == []                          # never raises

def test_history_annotate_merges_existing_only(tmp_path):
    h = History.load(tmp_path / "h.json")
    h.record("2026-08-08", "GME", 5.0, 5, 0, 0.0, 30.0, "hot")
    assert h.annotate("2026-08-08", "GME", ts_bull=61.0, ts_comments=150) is True
    assert h.data["GME"]["2026-08-08"]["ts_bull"] == 61.0
    assert h.data["GME"]["2026-08-08"]["weighted"] == 5.0    # core fields intact
    assert h.annotate("2026-08-08", "ZZZ", ts_bull=1.0) is False   # no record -> no create
    assert "ZZZ" not in h.data                               # baseline() safety: never a
                                                             # day-record without 'weighted'
```

- [ ] **Step 3: Run to verify failure** — `python -m pytest tests/test_tradestie.py -q` → FAIL (module missing).

- [ ] **Step 4: Implement `radar/tradestie.py`**

```python
"""Tradestie WSB sentiment — free, keyless directional (Bullish/Bearish) per-ticker
sentiment for the top-50 r/wallstreetbets names (api.tradestie.com, 15-min refresh,
20 req/min limit; we make one call per day).

Two jobs: (1) annotate history.json with ts_bull/ts_comments so directional-sentiment
history accrues from today; (2) serve as a partial-board fallback when ApeWisdom is
down (top-50 WSB only). sentiment_score is a VADER-style compound in [-1, 1] per the
recorded fixture; bull_pct maps it to 0-100."""
from __future__ import annotations

import time
from dataclasses import dataclass

import requests

from radar import degrade
from radar.apewisdom import Aggregate

DEFAULT_URL = "https://api.tradestie.com/v1/apps/reddit"


@dataclass
class TsRow:
    ticker: str
    sentiment: str      # "Bullish" | "Bearish"
    score: float        # compound score, -1..1
    comments: int


def parse_feed(raw) -> list[TsRow]:
    """Pure, resilient parser. Never raises."""
    out: list[TsRow] = []
    if not isinstance(raw, list):
        return out
    for r in raw:
        if not isinstance(r, dict):
            continue
        tok = str(r.get("ticker") or "").upper().strip()
        if not tok:
            continue
        try:
            score = float(r.get("sentiment_score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        try:
            comments = max(0, int(r.get("no_of_comments") or 0))
        except (TypeError, ValueError):
            comments = 0
        out.append(TsRow(ticker=tok, sentiment=str(r.get("sentiment") or ""),
                         score=score, comments=comments))
    return out


def bull_pct(score: float) -> float:
    """Compound score -1..1 -> bullish share 0..100, clamped."""
    return round(50.0 * (1.0 + max(-1.0, min(1.0, score))), 1)


def _get(url: str, ua: str, retries: int, sleep_s: float):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers={"User-Agent": ua}, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503):
                time.sleep(sleep_s * (2 ** attempt)); continue
            return None
        except requests.RequestException:
            time.sleep(sleep_s * (2 ** attempt))
    return None


def fetch_wsb(cfg) -> list[TsRow]:
    """One daily pull of the WSB top-50. Fail-soft: [] + degrade.warn on any failure."""
    ts = getattr(cfg, "tradestie", None)
    url = getattr(ts, "url", DEFAULT_URL)
    ua = getattr(ts, "user_agent", "reddit-signal-radar/0.1 (open-source ticker signal bot)")
    retries = int(getattr(ts, "max_retries", 3))
    sleep_s = float(getattr(ts, "sleep_seconds", 1.0))
    raw = _get(url, ua, retries, sleep_s)
    rows = parse_feed(raw)
    if not rows:
        degrade.warn("tradestie sentiment", "fetch returned nothing")
    return rows


def to_aggregates(rows: list[TsRow]) -> list[Aggregate]:
    """Fallback board input when ApeWisdom is empty: comment counts stand in for
    mentions (same attention semantics, narrower universe)."""
    return [Aggregate(ticker=r.ticker, name="", mentions=r.comments,
                      mentions_24h_ago=0, upvotes=0, subreddit="wallstreetbets")
            for r in rows if r.comments > 0]
```

- [ ] **Step 5: Add `History.annotate`.** In `radar/history.py`, after `record()`:

```python
    def annotate(self, day: str, ticker: str, **fields) -> bool:
        """Merge extra keys (e.g. ts_bull) into an EXISTING day-record. Never creates
        a record: baseline() requires 'weighted' in every day-record, so a ticker not
        scored today simply drops its annotation. Returns whether it merged."""
        rec = self.data.get(ticker, {}).get(day)
        if rec is None:
            return False
        rec.update(fields)
        return True
```

- [ ] **Step 6: Config block.** In `config.yaml`, append (top level, after the `apewisdom` block):

```yaml
tradestie:
  url: "https://api.tradestie.com/v1/apps/reddit"
  max_retries: 3
  sleep_seconds: 1.0
```

- [ ] **Step 7: Wire into run.py.** Add import `from radar import tradestie`. Directly after `aggregates = fetch_mentions(cfg)` (line ~51):

```python
    ts_rows = tradestie.fetch_wsb(cfg)                  # directional sentiment (fail-soft)
    board_source = "apewisdom"
    if not aggregates and ts_rows:                      # ApeWisdom down -> partial WSB board
        degrade.warn("apewisdom empty", "falling back to tradestie top-50 board")
        aggregates = tradestie.to_aggregates(ts_rows)
        board_source = "tradestie-fallback"
```

Then, directly after the `history.record(...)` loop (so records exist to annotate):

```python
    ts_by = {r.ticker: r for r in ts_rows}
    for s in signals:
        r = ts_by.get(s.ticker)
        if r:
            history.annotate(run_day, s.ticker,
                             ts_bull=tradestie.bull_pct(r.score), ts_comments=r.comments)
```

(`board_source` is consumed in Task 3.)

- [ ] **Step 8: Run everything** — `python -m pytest -q` → green (the live-fixture test runs offline against the recorded file).

- [ ] **Step 9: Commit**

```bash
git add radar/tradestie.py radar/history.py radar/run.py config.yaml tests/test_tradestie.py tests/fixtures/tradestie.json
git commit -m "feat(measure): Tradestie WSB directional sentiment — history annotation + ApeWisdom fallback"
```

---

### Task 3: Named source checks in health

**Files:**
- Modify: `radar/health.py` (`assess()`), `radar/run.py` (call site, line ~94), `tests/test_health.py`

**Interfaces:**
- Consumes: `board_source` and `ts_rows` from Task 2's run.py wiring.
- Produces: `assess(board, events, deepseek_key_present, sources=None)` — `health["sources"]` = the dict passed in (or `{}`). Values are strings: `"ok"`, `"down"`, `"fallback"`. Downstream consumers gate on `health.sources.<name>`.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_health.py`:

```python
def test_sources_block_passthrough():
    from radar.health import assess
    h = assess([], [], False, sources={"apewisdom": "down", "tradestie": "ok"})
    assert h["sources"] == {"apewisdom": "down", "tradestie": "ok"}

def test_sources_block_defaults_empty():
    from radar.health import assess
    assert assess([], [], False)["sources"] == {}
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_health.py -q` → FAIL (unexpected keyword / KeyError).

- [ ] **Step 3: Implement.** In `radar/health.py`, change the signature and return:

```python
def assess(board, events: list[dict], deepseek_key_present: bool,
           sources: dict | None = None) -> dict:
```

and the return statement to:

```python
    return {"status": status, "severe": severe, "problems": problems,
            "board_size": len(board), "sources": dict(sources or {})}
```

- [ ] **Step 4: Update the run.py call site** (line ~94):

```python
    health = assess_health(board, degrade.events(),
                           bool(os.environ.get("DEEPSEEK_API_KEY")),
                           sources={
                               "apewisdom": ("ok" if board_source == "apewisdom" and board
                                             else "down"),
                               "tradestie": ("fallback" if board_source == "tradestie-fallback"
                                             else ("ok" if ts_rows else "down"))})
```

- [ ] **Step 5: Full suite** — `python -m pytest -q` → green.

- [ ] **Step 6: Commit**

```bash
git add radar/health.py radar/run.py tests/test_health.py
git commit -m "feat(measure): named per-source checks in health.json"
```

---

### Task 4: Backtest core (`radar/backtest.py`)

**Files:**
- Create: `radar/backtest.py`, `tests/test_backtest.py`

**Interfaces:**
- Consumes: history dict (schema in Global Constraints), plays list (Task 1 schema), yfinance 1.5.2.
- Produces (all pure unless noted; prices arg is `{sym: {day: {"open": float, "close": float}}}`):
  - `trading_days(prices, benchmark="SPY") -> list[str]` — sorted day strings from the benchmark's price keys
  - `entry_index(days: list[str], signal_day: str) -> int | None` — index of first trading day STRICTLY after signal_day (None if off the end) — the look-ahead gate every other function must use
  - `window_return(prices, sym, days, i0, h) -> float | None` — `open[days[i0+h]] / open[days[i0]] - 1`
  - `excess_return(prices, sym, days, i0, h, benchmark="SPY") -> float | None`
  - `spearman(xs, ys) -> float`
  - `quintile_table(history, prices, days, horizon, benchmark="SPY") -> dict`
  - `rank_ic(history, prices, days, horizon) -> dict` — `{"mean","t","days"}` (Newey-West, lag=horizon)
  - `event_study(history, prices, days) -> dict` — `{"n_events", "car": {offset: mean}}`, events = transitions into `"hot"`
  - `vol_quintiles(history, prices, days, horizon=10) -> dict`
  - `scorecard(plays, prices, days, benchmark="SPY") -> dict`
  - `fetch_prices(tickers, start, end) -> dict` (network; per-ticker fail-soft)
  - `run_backtest(history_path, plays_path, out_path) -> dict` + `main(argv) -> int` (CLI: `--out out`)
  - `REGIME_NOTES` constant; `power(history) -> dict`

- [ ] **Step 1: Write the failing tests** — deterministic synthetic prices; no network:

```python
# tests/test_backtest.py
import json
from radar.backtest import (trading_days, entry_index, window_return, excess_return,
                            spearman, quintile_table, rank_ic, event_study,
                            vol_quintiles, scorecard, power, REGIME_NOTES)

def _prices(series):     # {sym: {day: open}} -> full price dicts (close = open)
    return {s: {d: {"open": v, "close": v} for d, v in days.items()} for s, days in series.items()}

DAYS = ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-06", "2026-07-07",
        "2026-07-08", "2026-07-09", "2026-07-10"]

def _flat(v=100.0):
    return {d: v for d in DAYS}

def test_trading_days_and_entry_index():
    p = _prices({"SPY": _flat()})
    days = trading_days(p)
    assert days == DAYS
    assert entry_index(days, "2026-07-03") == 3          # weekend skipped -> Mon 07-06
    assert entry_index(days, "2026-07-01") == 1
    assert entry_index(days, "2026-07-10") is None       # nothing strictly after
    assert entry_index(days, "2026-06-01") == 0

def test_lookahead_gate_never_prices_signal_day():
    # THE invariant: entry is strictly after the signal day, so a same-day price move
    # can never flatter the signal. 2026-07-02 doubles; signal fired ON 07-02 must
    # enter at 07-03 (100.0) and see 0% -- not +100%.
    p = _prices({"AAA": {**_flat(), "2026-07-02": 200.0},
                 "SPY": _flat()})
    days = trading_days(p)
    i0 = entry_index(days, "2026-07-02")
    assert days[i0] == "2026-07-03"
    assert window_return(p, "AAA", days, i0, 1) == 0.0

def test_window_and_excess_return():
    up = {d: 100.0 + i for i, d in enumerate(DAYS)}      # ~+1%/day
    p = _prices({"AAA": up, "SPY": _flat()})
    days = trading_days(p)
    r = window_return(p, "AAA", days, 0, 1)
    assert abs(r - 0.01) < 1e-9
    assert abs(excess_return(p, "AAA", days, 0, 1) - 0.01) < 1e-9   # flat benchmark
    assert window_return(p, "AAA", days, 5, 99) is None  # off the end
    assert window_return(p, "MISSING", days, 0, 1) is None

def test_spearman_known_values():
    assert abs(spearman([1, 2, 3, 4], [10, 20, 30, 40]) - 1.0) < 1e-9
    assert abs(spearman([1, 2, 3, 4], [40, 30, 20, 10]) + 1.0) < 1e-9
    assert spearman([1, 1, 1], [1, 2, 3]) == 0.0         # degenerate -> 0, not crash

def test_quintiles_separate_good_from_bad():
    # 10 tickers, one signal day. Scores 1..10; forward return proportional to score.
    hist = {f"T{i}": {"2026-07-01": {"weighted": 1.0, "raw": 5, "authors": 0,
                                     "pct_bull": 0, "score": float(i), "state": "hot"}}
            for i in range(1, 11)}
    series = {f"T{i}": {d: 100.0 * (1 + 0.001 * i) ** n for n, d in enumerate(DAYS)}
              for i in range(1, 11)}
    series["SPY"] = _flat()
    p = _prices(series)
    days = trading_days(p)
    q = quintile_table(hist, p, days, horizon=1)
    assert q["n"] == 10
    assert q["q5"]["mean_excess"] > q["q1"]["mean_excess"]
    assert q["spread"] > 0

def test_rank_ic_positive_when_score_predicts():
    hist = {f"T{i}": {d: {"weighted": 1.0, "raw": 5, "authors": 0, "pct_bull": 0,
                          "score": float(i), "state": "hot"}
                      for d in DAYS[:5]}
            for i in range(1, 11)}
    series = {f"T{i}": {d: 100.0 * (1 + 0.001 * i) ** n for n, d in enumerate(DAYS)}
              for i in range(1, 11)}
    series["SPY"] = _flat()
    p = _prices(series)
    ic = rank_ic(hist, p, trading_days(p), horizon=1)
    assert ic["mean"] > 0.9 and ic["days"] >= 4

def test_event_study_counts_hot_transitions():
    hist = {"AAA": {"2026-07-01": {"weighted": 1, "raw": 5, "authors": 0, "pct_bull": 0,
                                   "score": 10.0, "state": "sustained"},
                    "2026-07-02": {"weighted": 9, "raw": 40, "authors": 0, "pct_bull": 0,
                                   "score": 90.0, "state": "hot"}}}   # transition -> 1 event
    p = _prices({"AAA": _flat(), "SPY": _flat()})
    es = event_study(hist, p, trading_days(p))
    assert es["n_events"] == 1
    assert "0" in es["car"] and "5" in es["car"]

def test_scorecard_grades_picks():
    plays = [{"date": "2026-07-01", "ticker": "AAA", "conviction": "high"},
             {"date": "2026-07-01", "ticker": "BBB", "conviction": "low"}]
    up = {d: 100.0 * (1.02 ** i) for i, d in enumerate(DAYS)}     # winner
    dn = {d: 100.0 * (0.98 ** i) for i, d in enumerate(DAYS)}     # loser
    p = _prices({"AAA": up, "BBB": dn, "SPY": _flat()})
    sc = scorecard(plays, p, trading_days(p))
    assert sc["n_picks"] == 2
    assert sc["win_rate_5d"] == 0.5
    assert sc["mean_excess_5d"] is not None
    assert sc["since"] == "2026-07-01"

def test_power_and_regime_notes():
    hist = {"AAA": {d: {"weighted": 1, "raw": 5, "authors": 0, "pct_bull": 0,
                        "score": 1.0, "state": "new"} for d in DAYS}}
    pw = power(hist)
    assert pw["days"] == len(DAYS) and pw["sufficient"] is False and pw["target_days"] == 150
    assert any("2026-08-07" in n["date"] for n in REGIME_NOTES)
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_backtest.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement `radar/backtest.py`**

```python
"""Self-grading backtest — does the velocity signal predict anything?

Pre-committed test set (spec 2026-08-07, no fishing beyond these): quintile forward
excess returns, daily rank IC, event study around hot-transitions, forward-volatility
quintiles, and the Early Plays scorecard. The look-ahead rule is structural: every
price window starts at entry_index() -- the first trading day STRICTLY after the
signal day. Effective sample size is DAYS, not ticker-days; power() says when the
read is real (>=150 days). Runs weekly (backtest.yml); must never touch the daily board.
"""
from __future__ import annotations

import argparse, json, math, statistics
from datetime import date, timedelta
from pathlib import Path

from radar.history import History
from radar.plays_log import load_picks

REGIME_NOTES = [
    {"date": "2026-08-07",
     "note": "PR #4 merged: history 'state' becomes board-relative for board names; "
             "noise floor min_mentions 5 -> 10."},
]
TARGET_DAYS = 150
HORIZONS = (1, 5, 10)


# ---------- price plumbing ----------

def trading_days(prices: dict, benchmark: str = "SPY") -> list[str]:
    return sorted((prices.get(benchmark) or {}).keys())


def entry_index(days: list[str], signal_day: str) -> int | None:
    """First trading day STRICTLY after signal_day — the look-ahead gate."""
    for i, d in enumerate(days):
        if d > signal_day:
            return i
    return None


def _open(prices, sym, day):
    rec = (prices.get(sym) or {}).get(day)
    return rec.get("open") if rec else None


def window_return(prices, sym, days, i0, h):
    if i0 is None or i0 + h >= len(days):
        return None
    a, b = _open(prices, sym, days[i0]), _open(prices, sym, days[i0 + h])
    if not a or b is None:
        return None
    return b / a - 1.0


def excess_return(prices, sym, days, i0, h, benchmark="SPY"):
    r, br = window_return(prices, sym, days, i0, h), window_return(prices, benchmark, days, i0, h)
    if r is None or br is None:
        return None
    return r - br


# ---------- stats ----------

def _rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):                       # average ranks for ties
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs, ys) -> float:
    if len(xs) < 2 or len(xs) != len(ys):
        return 0.0
    rx, ry = _rank(xs), _rank(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def _newey_west_t(series: list[float], lag: int) -> float:
    """t-stat of the mean with Newey-West (Bartlett) correction for overlap."""
    n = len(series)
    if n < 3:
        return 0.0
    mean = statistics.fmean(series)
    e = [x - mean for x in series]
    var = sum(v * v for v in e) / n
    for k in range(1, min(lag, n - 1) + 1):
        w = 1.0 - k / (lag + 1.0)
        var += 2.0 * w * sum(e[i] * e[i - k] for i in range(k, n)) / n
    if var <= 0:
        return 0.0
    return mean / math.sqrt(var / n)


# ---------- signal frames ----------

def _frames(history: dict):
    """{day: [(ticker, score)]} for every recorded ticker-day."""
    frames: dict[str, list] = {}
    for t, days in history.items():
        for d, rec in days.items():
            frames.setdefault(d, []).append((t, float(rec.get("score") or 0.0)))
    return frames


def _quintile(rows_sorted, q):                  # q in 1..5, rows sorted ascending by score
    n = len(rows_sorted)
    lo, hi = (q - 1) * n // 5, q * n // 5
    return rows_sorted[lo:hi]


# ---------- the pre-committed tests ----------

def quintile_table(history, prices, days, horizon, benchmark="SPY"):
    per_q = {q: [] for q in range(1, 6)}
    n_total = 0
    for day, rows in _frames(history).items():
        i0 = entry_index(days, day)
        if i0 is None or len(rows) < 5:
            continue
        rows_sorted = sorted(rows, key=lambda r: r[1])
        for q in range(1, 6):
            for t, _score in _quintile(rows_sorted, q):
                r = excess_return(prices, t, days, i0, horizon, benchmark)
                if r is not None:
                    per_q[q].append(r); n_total += 1
    out = {"horizon": horizon, "n": n_total}
    for q in range(1, 6):
        vals = per_q[q]
        out[f"q{q}"] = {"mean_excess": (statistics.fmean(vals) if vals else None),
                        "n": len(vals)}
    q1, q5 = out["q1"]["mean_excess"], out["q5"]["mean_excess"]
    out["spread"] = (q5 - q1) if (q1 is not None and q5 is not None) else None
    return out


def rank_ic(history, prices, days, horizon):
    ics = []
    for day, rows in sorted(_frames(history).items()):
        i0 = entry_index(days, day)
        if i0 is None or len(rows) < 5:
            continue
        scores, rets = [], []
        for t, score in rows:
            r = excess_return(prices, t, days, i0, horizon)
            if r is not None:
                scores.append(score); rets.append(r)
        if len(scores) >= 5:
            ics.append(spearman(scores, rets))
    if not ics:
        return {"mean": None, "t": None, "days": 0}
    return {"mean": statistics.fmean(ics), "t": _newey_west_t(ics, lag=horizon),
            "days": len(ics)}


def event_study(history, prices, days, pre=5, post=20):
    """Mean cumulative excess (close-to-close log) return around transitions INTO 'hot'."""
    events = []
    for t, tdays in history.items():
        ordered = sorted(tdays)
        for prev, cur in zip(ordered, ordered[1:]):
            if tdays[cur].get("state") == "hot" and tdays[prev].get("state") != "hot":
                events.append((t, cur))

    def _close(sym, day):
        rec = (prices.get(sym) or {}).get(day)
        return rec.get("close") if rec else None

    sums, counts = {}, {}
    for t, day0 in events:
        i0 = entry_index(days, day0)
        if i0 is None:
            continue
        car = 0.0
        for off in range(-pre, post + 1):
            i = i0 + off
            if 1 <= i < len(days):
                a, b = _close(t, days[i - 1]), _close(t, days[i])
                ba, bb = _close("SPY", days[i - 1]), _close("SPY", days[i])
                if a and b and ba and bb:
                    car += math.log(b / a) - math.log(bb / ba)
            sums[off] = sums.get(off, 0.0) + car
            counts[off] = counts.get(off, 0) + 1
    car_mean = {str(off): (sums[off] / counts[off]) for off in sorted(sums)}
    return {"n_events": len(events), "car": car_mean}


def vol_quintiles(history, prices, days, horizon=10):
    """Forward realized vol (stdev of daily close-to-close log returns, annualized)."""
    def _fwd_vol(t, i0):
        rets = []
        for i in range(i0 + 1, min(i0 + 1 + horizon, len(days))):
            a = (prices.get(t) or {}).get(days[i - 1], {}).get("close")
            b = (prices.get(t) or {}).get(days[i], {}).get("close")
            if a and b:
                rets.append(math.log(b / a))
        if len(rets) < 3:
            return None
        return statistics.pstdev(rets) * math.sqrt(252)

    per_q = {q: [] for q in range(1, 6)}
    for day, rows in _frames(history).items():
        i0 = entry_index(days, day)
        if i0 is None or len(rows) < 5:
            continue
        rows_sorted = sorted(rows, key=lambda r: r[1])
        for q in range(1, 6):
            for t, _s in _quintile(rows_sorted, q):
                v = _fwd_vol(t, i0)
                if v is not None:
                    per_q[q].append(v)
    return {f"q{q}": (statistics.fmean(v) if (v := per_q[q]) else None) for q in range(1, 6)}


def scorecard(plays, prices, days, benchmark="SPY"):
    """Grade every logged Early Plays pick from its first tradeable open."""
    rows = []
    for pk in plays:
        i0 = entry_index(days, pk.get("date", ""))
        row = {"date": pk.get("date"), "ticker": pk.get("ticker"),
               "conviction": pk.get("conviction", ""),
               "excess_5d": excess_return(prices, pk.get("ticker"), days, i0, 5, benchmark),
               "excess_10d": excess_return(prices, pk.get("ticker"), days, i0, 10, benchmark)}
        rows.append(row)
    g5 = [r["excess_5d"] for r in rows if r["excess_5d"] is not None]
    g10 = [r["excess_10d"] for r in rows if r["excess_10d"] is not None]
    return {"n_picks": len(rows),
            "since": min((r["date"] for r in rows if r["date"]), default=None),
            "mean_excess_5d": (statistics.fmean(g5) if g5 else None),
            "mean_excess_10d": (statistics.fmean(g10) if g10 else None),
            "win_rate_5d": (sum(1 for x in g5 if x > 0) / len(g5) if g5 else None),
            "win_rate_10d": (sum(1 for x in g10 if x > 0) / len(g10) if g10 else None),
            "picks": rows,
            "disclaimer": "Hypothetical, frictionless, benchmark-adjusted. Not investment advice."}


def power(history: dict) -> dict:
    days = {d for t in history.values() for d in t}
    return {"days": len(days), "sufficient": len(days) >= TARGET_DAYS,
            "target_days": TARGET_DAYS}


# ---------- orchestration (network + I/O) ----------

def fetch_prices(tickers, start: str, end: str) -> dict:
    """Daily open/close via yfinance batch download. Per-ticker fail-soft: a symbol
    Yahoo can't price is simply absent (every consumer treats missing as None)."""
    from radar import degrade
    out: dict = {}
    try:
        import yfinance as yf
        data = yf.download(sorted(set(tickers)), start=start, end=end,
                           interval="1d", auto_adjust=True, progress=False,
                           group_by="ticker", threads=True)
    except Exception as e:
        degrade.warn("backtest price download", e)
        return out
    for t in set(tickers):
        try:
            df = data[t] if len(set(tickers)) > 1 else data
            for idx, row in df.iterrows():
                o, c = float(row["Open"]), float(row["Close"])
                if o > 0 and c > 0 and o == o and c == c:          # NaN-safe
                    out.setdefault(t, {})[idx.strftime("%Y-%m-%d")] = {"open": o, "close": c}
        except Exception:
            continue                                               # symbol missing -> skip
    return out


def _board_universe(history: dict) -> set[str]:
    """Tickers worth pricing: anything that ever reached a top-quintile score frame.
    Keeps the yfinance batch bounded (~hundreds, not thousands)."""
    keep: set[str] = set()
    for day, rows in _frames(history).items():
        rows_sorted = sorted(rows, key=lambda r: r[1])
        keep.update(t for t, _s in _quintile(rows_sorted, 5))
    return keep


def run_backtest(history_path="data/history.json", plays_path="data/plays_log.json",
                 out_path="out/backtest.json") -> dict:
    history = History.load(history_path).data
    plays = load_picks(plays_path)
    all_days = sorted({d for t in history.values() for d in t})
    if not all_days:
        result = {"error": "no history", "power": power(history)}
    else:
        start = (date.fromisoformat(all_days[0]) - timedelta(days=10)).isoformat()
        end = (date.fromisoformat(all_days[-1]) + timedelta(days=25)).isoformat()
        tickers = (_board_universe(history)
                   | {p.get("ticker") for p in plays if p.get("ticker")}
                   | {"SPY", "IWM"})
        prices = fetch_prices(tickers, start, end)
        days = trading_days(prices)
        result = {
            "as_of": all_days[-1],
            "power": power(history),
            "regime_notes": REGIME_NOTES,
            "quintiles": {str(h): quintile_table(history, prices, days, h) for h in HORIZONS},
            "quintiles_iwm": {str(h): quintile_table(history, prices, days, h, benchmark="IWM")
                              for h in HORIZONS},
            "rank_ic": {str(h): rank_ic(history, prices, days, h) for h in HORIZONS},
            "event_study": event_study(history, prices, days),
            "vol_test": vol_quintiles(history, prices, days),
            "scorecard": scorecard(plays, prices, days),
        }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1))
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", default="data/history.json")
    ap.add_argument("--plays", default="data/plays_log.json")
    ap.add_argument("--out", default="out")
    args = ap.parse_args(argv)
    result = run_backtest(args.history, args.plays, str(Path(args.out) / "backtest.json"))
    pw = result.get("power", {})
    print(f"backtest: {pw.get('days', 0)} days of history "
          f"(sufficient={pw.get('sufficient')}); wrote backtest.json")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
```

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_backtest.py -q` → 9 passed. Fix any drift between test expectations and implementation (the tests are the contract).

- [ ] **Step 5: One live smoke run** (network; not part of the suite):

```bash
git show origin/data:data/history.json > /tmp/hist.json 2>/dev/null || cp data/history.json /tmp/hist.json
python -m radar.backtest --history /tmp/hist.json --plays data/plays_log.json --out /tmp/bt
python -c "import json; d=json.load(open('/tmp/bt/backtest.json')); print(d['power'], d['rank_ic']['1'])"
```

Expected: a populated backtest.json with `power.days` ≈ 66+, IC numbers present (small |IC| is a finding, not a failure).

- [ ] **Step 6: Full suite** — `python -m pytest -q` → green.

- [ ] **Step 7: Commit**

```bash
git add radar/backtest.py tests/test_backtest.py
git commit -m "feat(measure): backtest harness — quintiles, rank IC, event study, vol test, scorecard"
```

---

### Task 5: Weekly backtest workflow + publication path

**Files:**
- Create: `.github/workflows/backtest.yml`
- Modify: `.github/workflows/daily.yml` (copy backtest.json into `out/` before upload, after the "Run pipeline" step)

**Interfaces:**
- Consumes: `python -m radar.backtest` CLI (Task 4); the data-branch overlay/commit-back pattern from daily.yml lines 24–59.
- Produces: `data/backtest.json` on the `data` branch (weekly); `out/backtest.json` on GitHub Pages (refreshed by the next daily run).

- [ ] **Step 1: Create `.github/workflows/backtest.yml`**

```yaml
name: weekly-backtest
on:
  schedule:
    - cron: "41 11 * * 0"      # Sunday 11:41 UTC — off the top of the hour on purpose
  workflow_dispatch: {}
permissions:
  contents: write              # commits data/backtest.json to the data branch
concurrency:
  group: pages                 # serialize with daily/fleet writers to the data branch
  cancel-in-progress: false
jobs:
  backtest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with: { ref: main, fetch-depth: 1 }
      - uses: actions/setup-python@v6
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt
      - name: Restore radar state (data branch)
        run: |
          if git fetch origin data; then
            git checkout FETCH_HEAD -- data/
          else
            echo "no data branch yet — cold start"
          fi
      - name: Run backtest
        run: python -m radar.backtest --out out
      - name: Commit backtest.json to data branch
        run: |
          git config user.name "radar-bot"
          git config user.email "radar-bot@users.noreply.github.com"
          if git fetch origin data; then
            git worktree add /tmp/state FETCH_HEAD
          else
            git worktree add --detach /tmp/state "$(git commit-tree "$(git mktree </dev/null)" -m 'state: seed')"
          fi
          mkdir -p /tmp/state/data
          cp -f out/backtest.json /tmp/state/data/backtest.json
          git -C /tmp/state add -A data
          git -C /tmp/state diff --cached --quiet || git -C /tmp/state commit -m "state: backtest $(date -u +%F)"
          git -C /tmp/state push origin HEAD:refs/heads/data
```

- [ ] **Step 2: Publish via the daily run.** In `.github/workflows/daily.yml`, after the "Run pipeline" step (line ~43), insert:

```yaml
      - name: Publish latest backtest alongside the board
        run: cp -f data/backtest.json out/backtest.json 2>/dev/null || echo "no backtest yet"
```

(The data-branch overlay earlier in the job already put `data/backtest.json` in place when it exists.)

- [ ] **Step 3: Validate workflow syntax** — `python -c "import yaml; yaml.safe_load(open('.github/workflows/backtest.yml')); yaml.safe_load(open('.github/workflows/daily.yml')); print('ok')"` → `ok`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/backtest.yml .github/workflows/daily.yml
git commit -m "ci(measure): weekly backtest workflow -> data branch; daily publishes backtest.json"
```

- [ ] **Step 5: After push, trigger once and verify** — `gh workflow run weekly-backtest && sleep 90 && gh run list --workflow weekly-backtest --limit 1`. Expected: success; then `git fetch origin data && git show origin/data:data/backtest.json | head -5` shows the document.

---

### Task 6: Daily scorecard block (data.json + dashboard card)

**Files:**
- Modify: `radar/run.py` (build scorecard, pass to `write_outputs` + template context), `radar/templates/dashboard.html.j2` (card after the `plays` block, line ~203), `tests/test_backtest.py` (append the daily-path test)

**Interfaces:**
- Consumes: `load_picks` (Task 1), `fetch_prices`/`trading_days`/`scorecard` (Task 4).
- Produces: `_daily_scorecard(run_day) -> dict | None` in run.py; `data.json` gains a top-level `"scorecard"` key (the Task 4 scorecard dict, or absent when unavailable); template context gains `scorecard`.

- [ ] **Step 1: Write the failing test.** Append to `tests/test_backtest.py`:

```python
def test_daily_scorecard_fail_soft(monkeypatch):
    # Network dead -> None, never an exception (the daily board must not care).
    import radar.run as run_mod
    monkeypatch.setattr("radar.backtest.fetch_prices", lambda *a, **k: {})
    assert run_mod._daily_scorecard("2026-08-08") is None
```

- [ ] **Step 2: Run to verify failure** — FAIL (`_daily_scorecard` missing).

- [ ] **Step 3: Implement in `radar/run.py`** (imports: `from radar import backtest`, `from radar.plays_log import load_picks`; place near `_early_plays`):

```python
def _daily_scorecard(run_day):
    """Grade all logged picks vs SPY — the cheap daily slice of the weekly backtest.
    Fail-soft: any problem returns None and the board ships without a scorecard."""
    try:
        plays = load_picks("data/plays_log.json")
        if not plays:
            return None
        from datetime import date, timedelta
        first = min(p["date"] for p in plays)
        start = (date.fromisoformat(first) - timedelta(days=5)).isoformat()
        tickers = {p["ticker"] for p in plays} | {"SPY"}
        prices = backtest.fetch_prices(tickers, start, run_day)
        days = backtest.trading_days(prices)
        if not days:
            return None
        return backtest.scorecard(plays, prices, days)
    except Exception as e:
        degrade.warn("daily scorecard", e)
        return None
```

Wire into `main()` after the plays-log append:

```python
    scorecard = _daily_scorecard(run_day) if not args.dry_run else None
```

then pass it through: add `scorecard=scorecard` to the `_build_context(...)` call, add a `scorecard=None` parameter to `_build_context` returning `scorecard=scorecard` in its dict, and extend the `write_outputs` call:

```python
    payload = {"board": [s.ticker for s in board], "health": health}
    if scorecard:
        payload["scorecard"] = scorecard
    write_outputs(html, payload, out_dir=args.out)
```

- [ ] **Step 4: Template card.** In `radar/templates/dashboard.html.j2`, directly after the `plays` block's closing `{% endif %}` (line ~203):

```jinja
  {% if scorecard and scorecard.n_picks %}
  <div class="plays">
    <div class="plays-tag">📊 Early Plays Track Record</div>
    <div class="plays-sub">
      {{ scorecard.n_picks }} picks since {{ scorecard.since }} ·
      {% if scorecard.mean_excess_10d is not none %}
        avg {{ "%+.1f"|format(scorecard.mean_excess_10d * 100) }}% vs SPY over 10 days ·
        win rate {{ "%.0f"|format((scorecard.win_rate_10d or 0) * 100) }}%
      {% else %}grading in progress — picks too fresh to score{% endif %}
    </div>
    <div class="plays-note">{{ scorecard.disclaimer }}</div>
  </div>
  {% endif %}
```

- [ ] **Step 5: Render test.** Append to `tests/test_backtest.py`:

```python
def test_template_renders_scorecard_block():
    from radar.render import render_html
    from radar.run import _build_context
    ctx = _build_context([], [], "2026-08-08", 0,
                         scorecard={"n_picks": 3, "since": "2026-08-01",
                                    "mean_excess_10d": 0.021, "win_rate_10d": 0.67,
                                    "mean_excess_5d": 0.01, "win_rate_5d": 0.5,
                                    "picks": [], "disclaimer": "Hypothetical. Not advice."})
    html = render_html(**ctx)
    assert "Early Plays Track Record" in html and "+2.1%" in html

def test_template_hides_scorecard_when_absent():
    from radar.render import render_html
    from radar.run import _build_context
    html = render_html(**_build_context([], [], "2026-08-08", 0))
    assert "Early Plays Track Record" not in html
```

- [ ] **Step 6: Full suite** — `python -m pytest -q` → green.

- [ ] **Step 7: Dry-run sanity** — `python3 -m radar.run --dry-run --no-email --out /tmp/o` exits 0 (scorecard skipped on dry-run).

- [ ] **Step 8: Commit**

```bash
git add radar/run.py radar/templates/dashboard.html.j2 tests/test_backtest.py
git commit -m "feat(measure): daily Early Plays scorecard in data.json + dashboard card"
```

---

### Task 7: Docs + roadmap close-out

**Files:**
- Modify: `README.md` (How it works + Configuration), `docs/ROADMAP.md` (decision log + Phase D backtest item)

**Interfaces:** none (docs only).

- [ ] **Step 1: README.** In the pipeline description (line ~19), extend to `fetch (ApeWisdom + Tradestie sentiment) → score → enrich → render → publish + email`, and document: `data/plays_log.json` + `data/backtest.json` in the data-branch list (line ~77), the `tradestie:` config block (Configuration section), the weekly `backtest.yml` workflow, and `out/backtest.json` + the `scorecard`/`sources` blocks in the artifacts description. Follow the file's existing tone; keep each addition to 1–3 lines.

- [ ] **Step 2: ROADMAP.** In `docs/ROADMAP.md`: check off Phase D's "Backtest the signal" with a pointer to `backtest.json`; add a decision-log entry dated with today's date summarizing Phase 1 (measurement layer + Tradestie clock + sources health), referencing the spec.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/ROADMAP.md
git commit -m "docs: measure-phase-1 — plays log, backtest, Tradestie, scorecard"
```

---

## Self-review notes (already applied)

- Spec coverage: 1a → Task 1; 1b → Tasks 4–6; 1c → Task 2; health checks → Task 3; publication path → Task 5; docs → Task 7. Phase 2 is a separate plan.
- The `pct_bull` field in history keeps its engagement semantics on the ApeWisdom path; directional sentiment lands as new `ts_bull`/`ts_comments` keys (spec's "fills the dead dimension" is delivered as parallel keys so old rows stay interpretable).
- `fetch_prices` uses `auto_adjust=True` — split/dividend-adjusted opens/closes; fine for excess returns.
- Survivorship caveat: delisted tickers priced as missing → excluded from means. `backtest.json` inherits this; acceptable at current fidelity (documented in module docstring).
