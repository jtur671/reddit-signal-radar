# Measure & Widen — Phase 2 Implementation Plan (Widen)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Widen the radar's signal per `docs/superpowers/specs/2026-08-07-measure-and-widen-design.md` (Phase 2): FINRA short-pressure, an 8-K material-event tripwire, CBOE options activity, Finnhub headlines, an inverse-Cramer feed, and a transparent composite score published per board row — every source accruing history from merge day.

**Architecture:** One module per source (`radar/shorts.py`, `radar/options.py`, `radar/cramer.py`, `radar/monitors/edgar_events.py`, Finnhub inside `radar/news.py`), each following the phase-1 contract: pure parser + fail-soft fetcher (`degrade.warn` breadcrumb), fields attached to board `Signal`s and annotated into `history.json` via `History.annotate` (clock accrual), and a named check in `health.json`'s `sources` block. `radar/composite.py` lands last, blending the components into a 0–100 with weights from `config.yaml`, published in a new top-level `signals` list in `data.json` (the `board`/`health`/`scorecard` keys are untouched — downstream contract preserved).

**Tech Stack:** Python 3.11, pytest, requests, jinja2. **No new dependencies.**

## Global Constraints

- Python floor **3.11**; every new module starts with `from __future__ import annotations`.
- **No new pip dependencies** (no pandas/numpy/scipy).
- Every network fetch: fail-soft, `degrade.warn("<source>", ...)` breadcrumb, never raises out; nothing may crash or block the daily board.
- History schema requires `weighted` in every day-record — `History.annotate` never creates records (it returns False for unrecorded tickers; that is the correct behavior, not an error).
- New data-branch state files must be added to `.gitignore` AND daily.yml's commit-back `cp` line.
- `data.json` existing keys (`board`, `health`, `scorecard`) keep their exact shapes; new output goes in NEW keys only.
- Source endpoints were live-verified 2026-08-07 (controller): FINRA CNMSshvol file (pipe-delimited, **fractional** volumes), CBOE delayed chain (`data.options[]` with `option`/`volume`/`open_interest`/`iv`), EDGAR EFTS full-text (needs explicit date bounding — unbounded queries return 2010-era hits), Mad Money dataset (`{"_schema": ..., "stocks": {TICKER: {company, mentions: [{date, sentiment, segment, note, closing_price}]}}}`, ~900 tickers), Finnhub company-news (key set as repo secret `FINNHUB_API_KEY`).
- Run tests with `python -m pytest -q` (CI) — locally `uv run --with-requirements requirements.txt -- python -m pytest -q` (baseline **248 passing**).
- Commit after every task; suite green at every commit; commit messages end with a blank line + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

## File Structure

**Create:**
- `radar/shorts.py`, `radar/options.py`, `radar/cramer.py`, `radar/composite.py`
- `radar/monitors/edgar_events.py`
- `tests/test_shorts.py`, `tests/test_options.py`, `tests/test_cramer.py`, `tests/test_composite.py`, `tests/test_edgar_events.py`
- `tests/fixtures/finra_shvol.txt`, `tests/fixtures/cboe_options.json` (trimmed), `tests/fixtures/cramer_sentiments.json` (trimmed), `tests/fixtures/finnhub_news.json`, `tests/fixtures/efts_8k.json`

**Modify:**
- `radar/models.py` — new optional Signal fields
- `radar/news.py` — Finnhub-first headline source with Google News fallback
- `radar/run.py` — per-source wiring + sources health + `signals` output list
- `radar/monitors/__init__.py` — register monitor #5
- `config.yaml` — `finra:`, `cboe:`, `cramer:`, `edgar_events:`, `composite:` blocks
- `.github/workflows/daily.yml` — cp line gains `data/cramer_snapshot.json`
- `.gitignore` — `data/cramer_snapshot.json`
- `radar/templates/dashboard.html.j2` — composite shown in the detail modal only (minimal)

---

### Task 1: Signal model fields (foundation)

**Files:**
- Modify: `radar/models.py`
- Test: covered by existing suite (dataclass defaults) — no new test file

**Interfaces:**
- Produces (all later tasks rely on these exact names): `Signal.short_ratio: float | None = None`, `Signal.pc_ratio: float | None = None`, `Signal.uoa: bool = False`, `Signal.cramer: str = ""`, `Signal.composite: int | None = None`, `Signal.components: dict = field(default_factory=dict)`

- [ ] **Step 1: Add the fields.** In `radar/models.py`, append to the `Signal` dataclass (after `days_running`):

```python
    short_ratio: float | None = None  # FINRA daily ShortVolume/TotalVolume (0..1)
    pc_ratio: float | None = None     # CBOE put/call volume ratio (top movers only)
    uoa: bool = False                 # unusual options activity flag (top movers only)
    cramer: str = ""                  # latest Mad Money sentiment enum ("" = no recent mention)
    composite: int | None = None      # 0-100 blended score (None until composite lands)
    components: dict = field(default_factory=dict)  # composite inputs, each 0-100 or None
```

- [ ] **Step 2: Full suite** — `uv run --with-requirements requirements.txt -- python -m pytest -q` → 248 passing (defaults are inert).

- [ ] **Step 3: Commit** — `git add radar/models.py && git commit -m "feat(widen): Signal fields for alt-data components"`

---

### Task 2: FINRA daily short-volume (`radar/shorts.py`)

**Files:**
- Create: `radar/shorts.py`, `tests/test_shorts.py`, `tests/fixtures/finra_shvol.txt`
- Modify: `radar/run.py`, `config.yaml`

**Interfaces:**
- Consumes: `cfg.finra` (url_template, max_lookback_days), `radar.degrade.warn`, `History.annotate`.
- Produces: `parse_shvol(text) -> dict[str, float]` (symbol → short_ratio 0..1, pure, never raises); `fetch_short_ratios(cfg, run_day: str) -> tuple[dict[str, float], str]` (ratios, source_date — walks back up to `max_lookback_days` calendar days from run_day−1 until a 200; `({}, "")` on total failure + warn).

- [ ] **Step 1: Record the fixture** (first ~15 lines of a real file are enough):

```bash
curl -s "https://cdn.finra.org/equity/regsho/daily/CNMSshvol20260806.txt" | head -15 > tests/fixtures/finra_shvol.txt
```

Expected shape: header `Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market`, then rows like `20260806|A|176779.078848|0|323438.701002|B,Q,N` (volumes are FRACTIONAL floats). If the real file ends with a trailer/total line, keep one in the fixture so the parser test covers skipping it.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_shorts.py
import pathlib
from radar.shorts import parse_shvol, fetch_short_ratios

def test_parse_shvol_from_fixture():
    text = pathlib.Path("tests/fixtures/finra_shvol.txt").read_text()
    ratios = parse_shvol(text)
    assert ratios, "fixture parsed to empty dict"
    for sym, r in ratios.items():
        assert 0.0 <= r <= 1.0, (sym, r)
    assert "A" in ratios and abs(ratios["A"] - 176779.078848 / 323438.701002) < 1e-9

def test_parse_shvol_never_raises_on_garbage():
    for text in (None, "", "not|a|real|file", "Date|Symbol\nx",
                 "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\nBAD|ROW\n20260806|Z|0|0|0|Q\n"):
        out = parse_shvol(text)
        assert isinstance(out, dict)
        assert "Z" not in out                     # TotalVolume 0 -> dropped, not div/0

def test_fetch_walks_back_and_fails_soft(monkeypatch):
    import radar.shorts as sh
    calls = []
    def fake_get(url, ua, retries=2, sleep_s=1.0):
        calls.append(url)
        return None if len(calls) < 3 else "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n20260804|GME|60|0|100|Q\n"
    monkeypatch.setattr(sh, "_get_text", fake_get)
    from types import SimpleNamespace
    cfg = SimpleNamespace(finra=SimpleNamespace(max_lookback_days=5))
    ratios, src = fetch_short_ratios(cfg, "2026-08-07")
    assert ratios == {"GME": 0.6} and src == "20260804"
    assert "20260806" in calls[0]                  # starts at run_day - 1

def test_fetch_total_failure_returns_empty(monkeypatch):
    import radar.shorts as sh
    monkeypatch.setattr(sh, "_get_text", lambda *a, **k: None)
    from types import SimpleNamespace
    cfg = SimpleNamespace(finra=SimpleNamespace(max_lookback_days=2))
    assert fetch_short_ratios(cfg, "2026-08-07") == ({}, "")
```

- [ ] **Step 3: Run to verify failure** — module missing.

- [ ] **Step 4: Implement**

```python
# radar/shorts.py
"""FINRA daily short-sale volume — a free, keyless short-pressure signal.

Reg SHO daily files (cdn.finra.org, one pipe-delimited file per trading day, ~500KB,
FRACTIONAL share volumes) give per-symbol ShortVolume/TotalVolume. The ratio is a daily
bearish-pressure / dark-pool proxy whose cadence matches the bot. Files exist only for
trading days, so the fetcher walks back from run_day-1 until it finds one."""
from __future__ import annotations

import time
from datetime import date, timedelta

import requests

from radar import degrade

URL_TEMPLATE = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{yyyymmdd}.txt"


def _get_text(url: str, ua: str, retries: int = 2, sleep_s: float = 1.0) -> str | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers={"User-Agent": ua}, timeout=20)
            if r.status_code == 200:
                return r.text
            if r.status_code in (429, 500, 502, 503):
                time.sleep(sleep_s * (2 ** attempt)); continue
            return None
        except requests.RequestException:
            time.sleep(sleep_s * (2 ** attempt))
    return None


def parse_shvol(text) -> dict[str, float]:
    """Pipe-delimited Reg SHO file -> {symbol: short_ratio}. Pure, never raises.
    Rows with unparsable or zero TotalVolume are dropped."""
    out: dict[str, float] = {}
    if not isinstance(text, str):
        return out
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) < 5 or parts[0] == "Date":
            continue
        sym = parts[1].strip().upper()
        try:
            short, total = float(parts[2]), float(parts[4])
        except ValueError:
            continue
        if not sym or total <= 0:
            continue
        out[sym] = max(0.0, min(1.0, short / total))
    return out


def fetch_short_ratios(cfg, run_day: str) -> tuple[dict[str, float], str]:
    """Latest available day's ratios, walking back from run_day-1 (weekends/holidays
    have no file). Fail-soft: ({}, "") + one warn after the walk is exhausted."""
    fc = getattr(cfg, "finra", None)
    lookback = int(getattr(fc, "max_lookback_days", 5))
    ua = "reddit-signal-radar/0.1 (open-source ticker signal bot)"
    d = date.fromisoformat(run_day)
    for back in range(1, lookback + 1):
        stamp = (d - timedelta(days=back)).strftime("%Y%m%d")
        text = _get_text(URL_TEMPLATE.format(yyyymmdd=stamp), ua)
        if text:
            ratios = parse_shvol(text)
            if ratios:
                return ratios, stamp
    degrade.warn("finra short volume", f"no file found in {lookback} days before {run_day}")
    return {}, ""
```

- [ ] **Step 5: Config block.** Append to `config.yaml`:

```yaml
finra:
  max_lookback_days: 5   # Reg SHO files exist only for trading days
```

- [ ] **Step 6: Wire into run.py.** Add import `from radar.shorts import fetch_short_ratios`. Directly after the Tradestie annotate loop (the `for s in signals:` loop that calls `history.annotate(..., ts_bull=...)`), add:

```python
    short_ratios, _shorts_day = fetch_short_ratios(cfg, run_day)   # fail-soft {} on outage
    for s in signals:
        r = short_ratios.get(s.ticker)
        if r is not None:
            s.short_ratio = round(r, 4)
            history.annotate(run_day, s.ticker, short_ratio=s.short_ratio)
```

and extend the `sources=` dict in the `assess_health(...)` call with:

```python
                               "finra": "ok" if short_ratios else "down",
```

- [ ] **Step 7: Full suite** → green (248 + 4 new). **Step 8: Commit** — `git add radar/shorts.py tests/test_shorts.py tests/fixtures/finra_shvol.txt radar/run.py config.yaml && git commit -m "feat(widen): FINRA daily short-volume ratio — enrichment + history clock"`

---

### Task 3: EDGAR 8-K material-event tripwire (`radar/monitors/edgar_events.py`)

**Files:**
- Create: `radar/monitors/edgar_events.py`, `tests/test_edgar_events.py`, `tests/fixtures/efts_8k.json`
- Modify: `radar/monitors/__init__.py`, `config.yaml`

**Interfaces:**
- Consumes: `radar.monitors.base.Signal`, `radar.monitors.edgar._http_get` (retry/backoff GET, `''` on failure), the fleet's `data/` overlay (history.json is available on fleet ticks).
- Produces: `EdgarEventsMonitor` (key=`"edgar8k"`, label=`"📢 8-K Event"`, card_style=`"insider"`, `fetch_new(seen) -> (signals, evaluated_ids)`, identity `validate`) registered as monitor #5. Watch-set helper `active_tickers(history_path, days=7) -> set[str]`.

- [ ] **Step 1: Verify EFTS date-bounding live and record the fixture.** The full-text endpoint returns 2010-era hits unbounded (controller-verified). Confirm the bounded form works, then record it:

```bash
curl -s -H "User-Agent: reddit-signal-radar admin@radar.local" \
  "https://efts.sec.gov/LATEST/search-index?q=%22material+definitive+agreement%22&forms=8-K&dateRange=custom&startdt=2026-08-06&enddt=2026-08-07" \
  | python3 -m json.tool | head -40
curl -s -H "User-Agent: reddit-signal-radar admin@radar.local" \
  "https://efts.sec.gov/LATEST/search-index?q=%22material+definitive+agreement%22&forms=8-K&dateRange=custom&startdt=2026-08-06&enddt=2026-08-07" \
  > tests/fixtures/efts_8k.json
```

Inspect: hits should carry `_source.ciks`, `_source.display_names` (e.g. `"Acme Corp  (ACME)  (CIK 0001234567)"`), `_source.file_date`, `_id` (accession:file). **If the date params are ignored (old file_date values in results), find the working parameter names from the EDGAR full-text search UI's network tab conventions (`startdt`/`enddt` are the documented ones) and adapt; if date bounding is truly unavailable, filter by `_source.file_date` client-side instead and say so in your report.** The fixture is ground truth for the parser.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_edgar_events.py
import json, pathlib
from radar.monitors.edgar_events import (EdgarEventsMonitor, parse_hits, ticker_from_display,
                                         active_tickers)

def test_ticker_from_display():
    assert ticker_from_display("Acme Corp  (ACME)  (CIK 0001234567)") == "ACME"
    assert ticker_from_display("No Ticker Holdings  (CIK 0009999999)") == ""
    assert ticker_from_display("") == ""

def test_parse_hits_from_fixture():
    raw = json.loads(pathlib.Path("tests/fixtures/efts_8k.json").read_text())
    rows = parse_hits(raw)
    assert isinstance(rows, list) and rows
    r = rows[0]
    assert set(r) >= {"id", "ticker", "display", "file_date", "url"}

def test_parse_hits_never_raises():
    for raw in (None, {}, {"hits": None}, {"hits": {"hits": [{"_id": "x"}]}}):
        assert isinstance(parse_hits(raw), list)

def test_active_tickers(tmp_path):
    hist = tmp_path / "history.json"
    hist.write_text(json.dumps({
        "AAA": {"2026-08-06": {"weighted": 1, "raw": 5, "authors": 0, "pct_bull": 0,
                                "score": 1.0, "state": "new"}},
        "OLD": {"2026-01-01": {"weighted": 1, "raw": 5, "authors": 0, "pct_bull": 0,
                                "score": 1.0, "state": "new"}}}))
    act = active_tickers(str(hist), days=7, today="2026-08-07")
    assert "AAA" in act and "OLD" not in act
    assert active_tickers(str(tmp_path / "missing.json"), days=7, today="2026-08-07") == set()

def test_monitor_filters_to_watchset_and_advances_cursor(monkeypatch):
    import radar.monitors.edgar_events as ee
    fixture = {"hits": {"hits": [
        {"_id": "acc1:doc.htm", "_source": {"display_names": ["Watched Co  (WTCH)  (CIK 1)"],
                                             "file_date": "2026-08-07"}},
        {"_id": "acc2:doc.htm", "_source": {"display_names": ["Ignored Co  (IGNR)  (CIK 2)"],
                                             "file_date": "2026-08-07"}},
    ]}}
    monkeypatch.setattr(ee, "_fetch_json", lambda url, ua: fixture)
    m = EdgarEventsMonitor(phrases=["material definitive agreement"], user_agent="t",
                            watch=lambda: {"WTCH"}, max_age_h=24)
    signals, evaluated = m.fetch_new(set())
    assert len(signals) == 1 and signals[0].tickers == ["WTCH"]
    assert set(evaluated) == {"acc1:doc.htm", "acc2:doc.htm"}   # non-hits advance the cursor too
    signals2, _ = m.fetch_new({"acc1:doc.htm", "acc2:doc.htm"})
    assert signals2 == []                                       # dedup works
```

- [ ] **Step 3: Run to verify failure** — module missing.

- [ ] **Step 4: Implement**

```python
# radar/monitors/edgar_events.py
"""8-K material-event tripwire (structured). Full-text-searches EDGAR (efts.sec.gov,
free, UA-header etiquette) for high-salience 8-K phrases filed in the last day, and
alerts when the filer maps to a ticker the radar is actively tracking (recent
history.json activity — the data branch is overlaid on fleet ticks). Date-bounds every
query: the unbounded endpoint returns decade-old filings."""
from __future__ import annotations

import json
import re
import urllib.parse
from datetime import date, timedelta
from pathlib import Path

from radar.monitors.base import Signal
from radar.monitors.edgar import _http_get

EFTS = ("https://efts.sec.gov/LATEST/search-index?q={q}&forms=8-K"
        "&dateRange=custom&startdt={start}&enddt={end}")
_DISPLAY_TICKER = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,9})\)\s*\(CIK")


def ticker_from_display(display: str) -> str:
    """EDGAR display_names embed the ticker: 'Acme Corp  (ACME)  (CIK 0001...)'."""
    m = _DISPLAY_TICKER.search(display or "")
    return m.group(1) if m else ""


def _fetch_json(url: str, ua: str):
    text = _http_get(url, ua)
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def parse_hits(raw) -> list[dict]:
    """EFTS response -> [{id, ticker, display, file_date, url}]. Pure, never raises."""
    out: list[dict] = []
    try:
        hits = raw["hits"]["hits"]
    except (TypeError, KeyError):
        return out
    for h in hits or []:
        if not isinstance(h, dict):
            continue
        src = h.get("_source") or {}
        display = (src.get("display_names") or [""])[0]
        acc = str(h.get("_id") or "")
        acc_no, _, fname = acc.partition(":")
        cik = str((src.get("ciks") or [""])[0]).lstrip("0")
        url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
               f"{acc_no.replace('-', '')}/{fname}"
               if cik and acc_no and fname
               else "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=8-K")
        out.append({
            "id": acc,
            "ticker": ticker_from_display(display),
            "display": display,
            "file_date": str(src.get("file_date") or ""),
            "url": url,
        })
    return out


def active_tickers(history_path: str = "data/history.json", days: int = 7,
                   today: str | None = None) -> set[str]:
    """Tickers with any history activity in the trailing window — the monitor's
    watch-set. Empty set (never an exception) when history is missing/corrupt."""
    try:
        data = json.loads(Path(history_path).read_text())
    except (OSError, ValueError):
        return set()
    t = date.fromisoformat(today) if today else date.today()
    cutoff = (t - timedelta(days=days)).isoformat()
    return {tick for tick, d in data.items()
            if isinstance(d, dict) and any(day >= cutoff for day in d)}


class EdgarEventsMonitor:
    """Fleet monitor #5 — see radar.monitors.base.Monitor for the contract."""
    def __init__(self, phrases: list[str], user_agent: str,
                 watch=active_tickers, max_age_h: int = 24):
        self.key, self.label, self.card_style = "edgar8k", "📢 8-K Event", "insider"
        self.max_age_h = max_age_h
        self.phrases = list(phrases)
        self.user_agent = user_agent
        self._watch = watch

    def fetch_new(self, seen: set[str]):
        watch = self._watch() if callable(self._watch) else set(self._watch)
        end = date.today().isoformat()
        start = (date.today() - timedelta(days=1)).isoformat()
        signals, evaluated = [], []
        for phrase in self.phrases:
            q = urllib.parse.quote(f'"{phrase}"', safe="")
            raw = _fetch_json(EFTS.format(q=q, start=start, end=end), self.user_agent)
            for row in parse_hits(raw):
                if row["id"] in seen or row["id"] in evaluated:
                    continue
                evaluated.append(row["id"])
                if row["ticker"] and row["ticker"] in watch:
                    signals.append(Signal(
                        tickers=[row["ticker"]],
                        summary=f"8-K “{phrase}” filed by {row['display']}",
                        url=row["url"], published=row["file_date"] + "T00:00:00Z",
                        monitor_key=self.key, link_text="EDGAR filing ↗"))
        return signals, evaluated

    def validate(self, signals):
        return signals
```

(If Step 1 showed date params are ignored, add a client-side `file_date >= start` filter in `fetch_new` — the test fixture stays valid either way.)

- [ ] **Step 5: Register + config.** In `config.yaml` append:

```yaml
edgar_events:
  phrases: ["material definitive agreement", "bankruptcy", "departure of directors or certain officers"]
  max_age_h: 24
  user_agent: "reddit-signal-radar admin@radar.local"
```

In `radar/monitors/__init__.py`: import `EdgarEventsMonitor` from `radar.monitors.edgar_events`, read `ev = cfg.edgar_events`, and append to the registry list:

```python
        EdgarEventsMonitor(
            phrases=list(ev.phrases), user_agent=ev.user_agent, max_age_h=ev.max_age_h,
        ),
```

- [ ] **Step 6: Full suite** → green. Check `tests/test_monitors_registry.py` — if it asserts a monitor count, update it (that is the one sanctioned existing-test change).

- [ ] **Step 7: Commit** — `git add radar/monitors/edgar_events.py radar/monitors/__init__.py tests/test_edgar_events.py tests/fixtures/efts_8k.json config.yaml [registry test if touched] && git commit -m "feat(widen): 8-K material-event tripwire — fleet monitor #5"`

---

### Task 4: Finnhub headlines in the news layer (`radar/news.py`)

**Files:**
- Modify: `radar/news.py`
- Create: `tests/fixtures/finnhub_news.json`; Test: extend `tests/test_about.py`? No — create `tests/test_finnhub_news.py`

**Interfaces:**
- Consumes: env `FINNHUB_API_KEY` (repo secret already set), existing `parse_news`/Google fallback.
- Produces: `finnhub_headlines(ticker, key, ua, days=5, max_items=6) -> list[str]` and a changed `headlines(...)`: Finnhub first when a key is present, Google News RSS fallback when Finnhub yields nothing. Signature of `headlines` is unchanged (run.py call sites untouched).

- [ ] **Step 1: Record the fixture**

```bash
curl -s "https://finnhub.io/api/v1/company-news?symbol=AAPL&from=2026-08-05&to=2026-08-07&token=$FINNHUB_API_KEY" | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)[:8]))" > tests/fixtures/finnhub_news.json
```

(Run with the key exported locally if available; if you have no key in your environment, construct the fixture from the documented shape — a JSON list of `{"datetime": <unix>, "headline": str, "source": str, ...}` — and note that in your report.)

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_finnhub_news.py
import json, pathlib
from radar.news import finnhub_headlines, parse_finnhub, headlines

def test_parse_finnhub_from_fixture():
    raw = json.loads(pathlib.Path("tests/fixtures/finnhub_news.json").read_text())
    titles = parse_finnhub(raw, max_items=6)
    assert titles and all(isinstance(t, str) and t for t in titles)
    assert len(titles) <= 6

def test_parse_finnhub_never_raises():
    for raw in (None, {}, [], [{"nope": 1}], [{"headline": ""}], "x"):
        assert isinstance(parse_finnhub(raw), list)

def test_headlines_prefers_finnhub_falls_back_to_google(monkeypatch):
    import radar.news as news
    monkeypatch.setenv("FINNHUB_API_KEY", "k")
    monkeypatch.setattr(news, "finnhub_headlines", lambda *a, **k: ["FH headline"])
    assert headlines("AAPL", "Apple") == ["FH headline"]
    monkeypatch.setattr(news, "finnhub_headlines", lambda *a, **k: [])
    monkeypatch.setattr(news, "_google_headlines", lambda *a, **k: ["G headline"])
    assert headlines("AAPL", "Apple") == ["G headline"]

def test_headlines_no_key_goes_straight_to_google(monkeypatch):
    import radar.news as news
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    called = []
    monkeypatch.setattr(news, "finnhub_headlines",
                        lambda *a, **k: called.append(1) or [])
    monkeypatch.setattr(news, "_google_headlines", lambda *a, **k: ["G"])
    assert headlines("AAPL") == ["G"] and not called
```

- [ ] **Step 3: Run to verify failure.**

- [ ] **Step 4: Implement.** In `radar/news.py`: rename the existing `headlines` body to `_google_headlines(ticker, name, ua, retries, sleep_s)` (identical logic, including its `warn`), add:

```python
import os
from datetime import timedelta

FINNHUB = ("https://finnhub.io/api/v1/company-news?symbol={sym}"
           "&from={start}&to={end}&token={key}")


def parse_finnhub(raw, max_items: int = 6) -> list[str]:
    """Finnhub company-news list -> recent headline titles. Pure, never raises."""
    out: list[str] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("headline") or "").strip()
        if title:
            out.append(title)
        if len(out) >= max_items:
            break
    return out


def finnhub_headlines(ticker: str, key: str, ua: str = "reddit-signal-radar/0.1",
                      days: int = 5, max_items: int = 6) -> list[str]:
    """Company headlines from Finnhub (60 calls/min free tier — one call per board
    ticker per day is far inside it). Never raises; [] on any failure."""
    end = datetime.now(timezone.utc).date()
    url = FINNHUB.format(sym=ticker, start=(end - timedelta(days=days)).isoformat(),
                         end=end.isoformat(), key=key)
    try:
        r = requests.get(url, headers={"User-Agent": ua}, timeout=15)
        if r.status_code == 200:
            return parse_finnhub(r.json(), max_items=max_items)
        warn(f"finnhub news {ticker}", f"HTTP {r.status_code}")
    except requests.RequestException as e:
        warn(f"finnhub news {ticker}", e)
    return []


def headlines(ticker: str, name: str = "", ua: str = "reddit-signal-radar/0.1",
              retries: int = 2, sleep_s: float = 1.0) -> list[str]:
    """Recent headlines: Finnhub when a key is configured (richer, per-symbol),
    Google News RSS otherwise or as fallback. Same signature as before."""
    key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if key:
        got = finnhub_headlines(ticker, key, ua)
        if got:
            return got
    return _google_headlines(ticker, name, ua, retries, sleep_s)
```

- [ ] **Step 5: Sources health.** In run.py's `sources=` dict add:

```python
                               "finnhub": ("ok" if os.environ.get("FINNHUB_API_KEY")
                                           else "unused"),
```

("ok" here means configured; per-call failures already surface as degrade events.)

- [ ] **Step 6: Full suite** → green. **Step 7: Commit** — `git add radar/news.py tests/test_finnhub_news.py tests/fixtures/finnhub_news.json radar/run.py && git commit -m "feat(widen): Finnhub-first headlines with Google News fallback"`

---

### Task 5: CBOE options activity (`radar/options.py`)

**Files:**
- Create: `radar/options.py`, `tests/test_options.py`, `tests/fixtures/cboe_options.json`
- Modify: `radar/run.py`, `config.yaml`

**Interfaces:**
- Consumes: `cfg.cboe` (top_n, uoa_vol_oi, min_volume), `History.annotate`.
- Produces: `parse_chain(raw) -> dict` (`{"pc_ratio": float|None, "call_vol": float, "put_vol": float, "total_vol": float, "total_oi": float}`, pure); `option_stats(ticker, cfg) -> dict | None` (network, fail-soft None); `is_put(symbol: str) -> bool | None` (OCC-style symbol classifier).

- [ ] **Step 1: Record a trimmed fixture** (full chain is 1.6MB — keep ~30 options):

```bash
curl -s "https://cdn.cboe.com/api/global/delayed_quotes/options/AAPL.json" | python3 -c "
import json,sys
d=json.load(sys.stdin)
d['data']['options']=d['data']['options'][:30]
json.dump(d,open('tests/fixtures/cboe_options.json','w'))"
```

Option symbols look like `AAPL260807C00110000` — root + YYMMDD + C/P + strike×1000. Rows carry `volume`, `open_interest`, `iv`.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_options.py
import json, pathlib
from radar.options import parse_chain, is_put, option_stats

def test_is_put_classifier():
    assert is_put("AAPL260807C00110000") is False
    assert is_put("AAPL260807P00110000") is True
    assert is_put("GARBAGE") is None
    assert is_put("") is None

def test_parse_chain_from_fixture():
    raw = json.loads(pathlib.Path("tests/fixtures/cboe_options.json").read_text())
    stats = parse_chain(raw)
    assert stats["total_vol"] >= 0 and stats["total_oi"] >= 0
    assert stats["pc_ratio"] is None or stats["pc_ratio"] >= 0

def test_parse_chain_math():
    raw = {"data": {"options": [
        {"option": "X260101C00010000", "volume": 30, "open_interest": 100},
        {"option": "X260101P00010000", "volume": 60, "open_interest": 100},
        {"option": "BAD", "volume": 5, "open_interest": 5},          # unclassifiable -> vol counted, not in P/C
    ]}}
    s = parse_chain(raw)
    assert s["call_vol"] == 30 and s["put_vol"] == 60
    assert abs(s["pc_ratio"] - 2.0) < 1e-9
    assert s["total_vol"] == 95 and s["total_oi"] == 205

def test_parse_chain_never_raises():
    for raw in (None, {}, {"data": {}}, {"data": {"options": ["x", {"volume": "?"}]}}):
        assert isinstance(parse_chain(raw), dict)

def test_option_stats_fail_soft(monkeypatch):
    import radar.options as op
    monkeypatch.setattr(op, "_get_json", lambda *a, **k: None)
    from types import SimpleNamespace
    assert option_stats("AAPL", SimpleNamespace(cboe=SimpleNamespace())) is None
```

- [ ] **Step 3: Run to verify failure.**

- [ ] **Step 4: Implement**

```python
# radar/options.py
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
```

- [ ] **Step 5: Config + wiring.** `config.yaml`:

```yaml
cboe:
  top_n: 10          # board movers to pull chains for (1.6MB each — keep small)
  uoa_vol_oi: 1.0    # flag when day volume > this multiple of open interest
  min_volume: 1000   # ...and at least this many contracts traded
```

In run.py, after the FINRA block (Task 2's wiring):

```python
    cboe_cfg = getattr(cfg, "cboe", None)
    cboe_hits = 0
    for s in board[:int(getattr(cboe_cfg, "top_n", 10))]:
        stats = option_stats(s.ticker, cfg)
        if stats is None:
            degrade.warn("cboe options", s.ticker)
            continue
        cboe_hits += 1
        if stats["pc_ratio"] is not None:
            s.pc_ratio = round(stats["pc_ratio"], 3)
        s.uoa = bool(stats["total_oi"] > 0
                     and stats["total_vol"] >= float(getattr(cboe_cfg, "min_volume", 1000))
                     and stats["total_vol"] / stats["total_oi"]
                         > float(getattr(cboe_cfg, "uoa_vol_oi", 1.0)))
        history.annotate(run_day, s.ticker, pc_ratio=s.pc_ratio, uoa=s.uoa)
```

(import `option_stats` from `radar.options`) and add to the `sources=` dict:

```python
                               "cboe": "ok" if cboe_hits else ("down" if board else "unused"),
```

- [ ] **Step 6: Full suite** → green. **Step 7: Commit** — `git add radar/options.py tests/test_options.py tests/fixtures/cboe_options.json radar/run.py config.yaml && git commit -m "feat(widen): CBOE put/call + UOA-lite for top board movers"`

---

### Task 6: Inverse-Cramer feed (`radar/cramer.py`)

**Files:**
- Create: `radar/cramer.py`, `tests/test_cramer.py`, `tests/fixtures/cramer_sentiments.json`
- Modify: `radar/run.py`, `config.yaml`, `.github/workflows/daily.yml` (cp line), `.gitignore`

**Interfaces:**
- Consumes: `cfg.cramer` (url, max_age_days, snapshot_path), `History.annotate`.
- Produces: `parse_sentiments(raw, today, max_age_days) -> dict[str, str]` (ticker → most-recent in-window sentiment enum, pure); `fetch_cramer(cfg, run_day) -> dict[str, str]` (network; vendors a snapshot to `snapshot_path` when content changed; falls back to the last snapshot when upstream is gone; `{}` + warn on total failure). Sentiment enums (from the dataset's `_schema`): `strong_buy, buy, mild_buy, buy_on_pullback, wait_hold_neutral, caution_concern, sell_avoid`.

- [ ] **Step 1: Record a trimmed fixture**

```bash
curl -s "https://raw.githubusercontent.com/jf-silverman/analyzing-stock-calls/main/data/stock_sentiments.json" | python3 -c "
import json,sys,itertools
d=json.load(sys.stdin)
d['stocks']=dict(itertools.islice(d['stocks'].items(), 12))
json.dump(d,open('tests/fixtures/cramer_sentiments.json','w'))"
```

Verified shape: `{"_schema": {...}, "stocks": {TICKER: {"company": str, "mentions": [{"date": "YYYY-MM-DD", "sentiment": enum, "segment": enum, "note": str, "closing_price": float}]}}}`.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_cramer.py
import json, pathlib
from radar.cramer import parse_sentiments, fetch_cramer

def _raw(mentions_by_ticker):
    return {"stocks": {t: {"company": t, "mentions": ms}
                       for t, ms in mentions_by_ticker.items()}}

def test_parse_takes_most_recent_within_window():
    raw = _raw({"NVDA": [
        {"date": "2026-07-01", "sentiment": "sell_avoid"},
        {"date": "2026-08-01", "sentiment": "strong_buy"},
    ]})
    out = parse_sentiments(raw, today="2026-08-07", max_age_days=30)
    assert out == {"NVDA": "strong_buy"}

def test_parse_drops_stale_and_garbage():
    raw = _raw({"OLD": [{"date": "2026-01-01", "sentiment": "buy"}],
                "BAD": [{"sentiment": "buy"}, "garbage"],
                "EMPTY": []})
    assert parse_sentiments(raw, today="2026-08-07", max_age_days=30) == {}
    for r in (None, {}, {"stocks": "x"}):
        assert parse_sentiments(r, today="2026-08-07", max_age_days=30) == {}

def test_parse_fixture():
    raw = json.loads(pathlib.Path("tests/fixtures/cramer_sentiments.json").read_text())
    out = parse_sentiments(raw, today="2026-08-07", max_age_days=3650)  # wide window: shape test
    assert out and all(isinstance(v, str) for v in out.values())

def test_fetch_vendors_snapshot_and_falls_back(tmp_path, monkeypatch):
    import radar.cramer as cr
    from types import SimpleNamespace
    snap = tmp_path / "cramer_snapshot.json"
    cfg = SimpleNamespace(cramer=SimpleNamespace(
        url="http://x", max_age_days=30, snapshot_path=str(snap)))
    live = _raw({"NVDA": [{"date": "2026-08-01", "sentiment": "strong_buy"}]})
    monkeypatch.setattr(cr, "_get_json", lambda *a, **k: live)
    assert fetch_cramer(cfg, "2026-08-07") == {"NVDA": "strong_buy"}
    assert snap.exists()                                   # vendored
    monkeypatch.setattr(cr, "_get_json", lambda *a, **k: None)
    assert fetch_cramer(cfg, "2026-08-07") == {"NVDA": "strong_buy"}   # snapshot fallback

def test_fetch_total_failure(tmp_path, monkeypatch):
    import radar.cramer as cr
    from types import SimpleNamespace
    cfg = SimpleNamespace(cramer=SimpleNamespace(
        url="http://x", max_age_days=30, snapshot_path=str(tmp_path / "none.json")))
    monkeypatch.setattr(cr, "_get_json", lambda *a, **k: None)
    assert fetch_cramer(cfg, "2026-08-07") == {}
```

- [ ] **Step 3: Run to verify failure.**

- [ ] **Step 4: Implement**

```python
# radar/cramer.py
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
```

- [ ] **Step 5: Config, wiring, plumbing.** `config.yaml`:

```yaml
cramer:
  url: "https://raw.githubusercontent.com/jf-silverman/analyzing-stock-calls/main/data/stock_sentiments.json"
  max_age_days: 30
  snapshot_path: "data/cramer_snapshot.json"
```

run.py (after the CBOE block; import `fetch_cramer`):

```python
    cramer_by = fetch_cramer(cfg, run_day) if not args.dry_run else {}
    for s in signals:
        c = cramer_by.get(s.ticker)
        if c:
            s.cramer = c
            history.annotate(run_day, s.ticker, cramer=c)
```

`sources=` dict addition: `"cramer": "ok" if cramer_by else "down",`
`.gitignore`: add `data/cramer_snapshot.json` next to the other data-branch state files.
`daily.yml` commit-back cp line: append `data/cramer_snapshot.json` to the existing multi-file `cp -f ... /tmp/state/data/` line.

- [ ] **Step 6: Full suite** → green. **Step 7: Commit** — `git add radar/cramer.py tests/test_cramer.py tests/fixtures/cramer_sentiments.json radar/run.py config.yaml .gitignore .github/workflows/daily.yml && git commit -m "feat(widen): inverse-Cramer feed — vendored Mad Money sentiment"`

---

### Task 7: Composite score (`radar/composite.py`) + `signals` output

**Files:**
- Create: `radar/composite.py`, `tests/test_composite.py`
- Modify: `radar/run.py`, `config.yaml`, `radar/templates/dashboard.html.j2` (detail modal only)

**Interfaces:**
- Consumes: every field from Tasks 1–6 plus `s.score`, `s.pct_bull` (engagement proxy), Tradestie's `ts_bull` (via history's day-record — see Step 4), fresh alerts from `_load_alerts` (already in run.py).
- Produces: `components_for(signal, board, ts_bull, alert_tickers) -> dict` (each value 0–100 float or None); `blend(components, weights) -> tuple[int | None, dict]` (composite 0–100 + the renormalized weights actually used; None when every component is None); config `composite.weights` mapping.

Component definitions (documented in the module docstring; each None when its source is absent):
- `velocity` — percentile rank of `s.score` within the displayed board (0–100).
- `direction` — Tradestie `ts_bull` (already 0–100) when covered, else None.
- `engagement` — `s.pct_bull` (the upvotes-per-mention proxy, already 0–100), None when 0 mentions.
- `short_pressure` — percentile rank of `s.short_ratio` within board members that have one.
- `options` — 100 if `s.uoa` else 50, only when `s.pc_ratio` is not None or `s.uoa`; None when CBOE didn't cover the name.
- `events` — 100 if the ticker appears in any FRESH monitor alert (the `alert_tickers` set from `_load_alerts` output), else 0. (Spec's "8-K count" generalized to all-monitor fresh-alert involvement — deviation noted for review.)
- `cramer_inverse` — inverse mapping of the enum: `sell_avoid`→100, `caution_concern`→80, `wait_hold_neutral`→50, `buy_on_pullback`→40, `mild_buy`→30, `buy`→20, `strong_buy`→0; None when no recent mention.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_composite.py
from radar.composite import blend, components_for, percentile_rank, CRAMER_INVERSE
from radar.models import Signal

def test_percentile_rank():
    assert percentile_rank(30.0, [10.0, 20.0, 30.0, 40.0]) == 75.0   # 3 of 4 <= value
    assert percentile_rank(5.0, [10.0]) == 0.0
    assert percentile_rank(1.0, []) is None

def test_blend_renormalizes_nulls():
    weights = {"a": 0.5, "b": 0.3, "c": 0.2}
    score, used = blend({"a": 100.0, "b": None, "c": 50.0}, weights)
    # a,c renormalized: 0.5/0.7 * 100 + 0.2/0.7 * 50 = 85.71 -> 86
    assert score == 86
    assert abs(sum(used.values()) - 1.0) < 1e-9 and "b" not in used

def test_blend_all_null():
    assert blend({"a": None}, {"a": 1.0}) == (None, {})

def test_components_for_shapes():
    s = Signal(ticker="AAA", score=50.0, pct_bull=40.0, short_ratio=0.5,
               pc_ratio=1.2, uoa=True, cramer="sell_avoid")
    peer = Signal(ticker="BBB", score=10.0, short_ratio=0.1)
    comps = components_for(s, [s, peer], ts_bull=61.0, alert_tickers={"AAA"})
    assert comps["velocity"] == 100.0 and comps["direction"] == 61.0
    assert comps["engagement"] == 40.0 and comps["short_pressure"] == 100.0
    assert comps["options"] == 100.0 and comps["events"] == 100.0
    assert comps["cramer_inverse"] == CRAMER_INVERSE["sell_avoid"] == 100.0

def test_components_none_when_uncovered():
    s = Signal(ticker="AAA", score=50.0)
    comps = components_for(s, [s], ts_bull=None, alert_tickers=set())
    assert comps["direction"] is None and comps["short_pressure"] is None
    assert comps["options"] is None and comps["cramer_inverse"] is None
    assert comps["events"] == 0.0
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement**

```python
# radar/composite.py
"""Transparent composite score — every component published beside the blend.

The consuming trading bot should trust the COMPONENTS more than the single number:
weights start as documented heuristics (config.yaml `composite.weights`) and get
recalibrated from measured ICs once backtest.json's power block turns sufficient
(a config change, not a code change). None components (source down / name uncovered)
are excluded with weight renormalization, and the weights actually used are published.

Component semantics: velocity = board-relative score percentile; direction = Tradestie
bullish share; engagement = upvotes-per-mention proxy; short_pressure = board-relative
short-ratio percentile; options = UOA flag (100) vs covered-but-quiet (50); events =
fresh monitor-alert involvement (any monitor, 0/100); cramer_inverse = inverted Mad
Money call (fade-the-call mapping)."""
from __future__ import annotations

CRAMER_INVERSE = {"sell_avoid": 100.0, "caution_concern": 80.0,
                  "wait_hold_neutral": 50.0, "buy_on_pullback": 40.0,
                  "mild_buy": 30.0, "buy": 20.0, "strong_buy": 0.0}

DEFAULT_WEIGHTS = {"velocity": 0.30, "direction": 0.15, "engagement": 0.10,
                   "short_pressure": 0.15, "options": 0.10, "events": 0.10,
                   "cramer_inverse": 0.10}


def percentile_rank(value, population) -> float | None:
    """Share of population <= value, 0-100. None on empty population."""
    pop = [p for p in population if p is not None]
    if not pop or value is None:
        return None
    return round(100.0 * sum(1 for p in pop if p <= value) / len(pop), 1)


def components_for(s, board, ts_bull, alert_tickers) -> dict:
    scores = [b.score for b in board]
    shorts = [b.short_ratio for b in board if b.short_ratio is not None]
    return {
        "velocity": percentile_rank(s.score, scores),
        "direction": (float(ts_bull) if ts_bull is not None else None),
        "engagement": (float(s.pct_bull) if s.pct_bull else None),
        "short_pressure": (percentile_rank(s.short_ratio, shorts)
                           if s.short_ratio is not None else None),
        "options": (100.0 if s.uoa else 50.0) if (s.uoa or s.pc_ratio is not None) else None,
        "events": 100.0 if s.ticker in alert_tickers else 0.0,
        "cramer_inverse": CRAMER_INVERSE.get(s.cramer) if s.cramer else None,
    }


def blend(components: dict, weights: dict) -> tuple[int | None, dict]:
    """Weighted mean over non-None components with renormalized weights.
    Returns (0-100 int or None, weights actually used summing to 1.0)."""
    live = {k: v for k, v in components.items()
            if v is not None and weights.get(k, 0) > 0}
    total_w = sum(weights[k] for k in live)
    if not live or total_w <= 0:
        return None, {}
    used = {k: weights[k] / total_w for k in live}
    score = sum(live[k] * used[k] for k in live)
    return int(round(max(0.0, min(100.0, score)))), used
```

- [ ] **Step 4: Config + run.py wiring.** `config.yaml`:

```yaml
composite:
  weights:            # heuristic until backtest.json power.sufficient; then recalibrate here
    velocity: 0.30
    direction: 0.15
    engagement: 0.10
    short_pressure: 0.15
    options: 0.10
    events: 0.10
    cramer_inverse: 0.10
```

In run.py, AFTER `alerts = _load_alerts("data")` (components need the fresh-alert set) and before `render_html`:

```python
    alert_tickers = {t.strip("$") for a in alerts for t in a["tickers"].split(" · ") if t}
    comp_cfg = getattr(cfg, "composite", None)
    weights = ({k: float(v) for k, v in vars(comp_cfg.weights).items()}
               if getattr(comp_cfg, "weights", None) else dict(DEFAULT_WEIGHTS))
    ts_by_bull = {r.ticker: tradestie.bull_pct(r.score) for r in ts_rows}
    for s in board:
        s.components = components_for(s, board, ts_by_bull.get(s.ticker), alert_tickers)
        s.composite, _used = blend(s.components, weights)
```

(weights never get mixed into the components dict — the payload publishes them separately). Build the machine-readable rows for data.json (extend the `payload` construction from phase 1):

```python
    payload = {"board": [s.ticker for s in board], "health": health,
               "signals": [dict(ticker=s.ticker, composite=s.composite,
                                components=s.components,
                                short_ratio=s.short_ratio, pc_ratio=s.pc_ratio,
                                uoa=s.uoa, cramer=s.cramer,
                                mentions=s.mentions, score=round(s.score, 2),
                                state=s.state, price=s.price)
                           for s in board],
               "weights": weights}
```

(imports: `from radar.composite import components_for, blend, DEFAULT_WEIGHTS`)

- [ ] **Step 5: Detail-modal line.** In `_detail_blob` (run.py), add `composite=s.composite,` to the per-ticker dict; in `dashboard.html.j2`'s detail modal, wherever the modal lists metrics, add one guarded line following the surrounding markup style, e.g. `{% if d.composite is not none %}<div>Composite {{ d.composite }}/100</div>{% endif %}` adapted to the modal's actual field markup (read the modal template section first and mimic it exactly).

- [ ] **Step 6: Integration test.** Append to `tests/test_composite.py`:

```python
def test_data_json_signals_block(tmp_path):
    # the payload contract the downstream bot reads
    from radar.render import write_outputs
    payload = {"board": ["AAA"], "health": {"status": "ok"},
               "signals": [{"ticker": "AAA", "composite": 61,
                            "components": {"velocity": 100.0}}],
               "weights": {"velocity": 1.0}}
    write_outputs("<html></html>", payload, out_dir=str(tmp_path))
    import json as j
    d = j.loads((tmp_path / "data.json").read_text())
    assert d["signals"][0]["composite"] == 61 and d["weights"]["velocity"] == 1.0
    assert d["board"] == ["AAA"]                      # legacy contract untouched
```

- [ ] **Step 7: Full suite** → green. **Step 8: Commit** — `git add radar/composite.py tests/test_composite.py radar/run.py config.yaml radar/templates/dashboard.html.j2 && git commit -m "feat(widen): transparent composite score + signals block in data.json"`

---

### Task 8: Docs close-out

**Files:**
- Modify: `README.md`, `docs/ROADMAP.md`, `docs/superpowers/specs/2026-08-07-measure-and-widen-design.md`

- [ ] **Step 1: README.** Document (matching the file's terse register, 1–3 lines each): the five new sources with their config blocks (`finra`, `cboe`, `cramer`, `edgar_events`, Finnhub via `FINNHUB_API_KEY` secret with Google News fallback), the 8-K monitor in the Monitor-fleet section, `data/cramer_snapshot.json` in the data-branch file list, and the `signals` + `weights` blocks in the data.json description (components > blend, weights heuristic until backtest power).
- [ ] **Step 2: ROADMAP.** Decision-log entry dated with the actual implementation date; note Phase C/D items this supersedes or advances if any obviously apply (read before editing).
- [ ] **Step 3: Spec.** In the spec's Phase 2 table, annotate each row Done with date; note the two sanctioned deviations (events component = all-monitor fresh-alert involvement rather than an 8-K count; Finnhub replaces-with-fallback rather than augments Google News).
- [ ] **Step 4: Full suite once** (docs-only, count unchanged) → commit `docs: widen-phase-2 — five sources, 8-K monitor, composite score`.

---

## Self-review notes (already applied)

- Spec 2a→Task 2, 2b→Task 5, 2c→Task 3, 2d→Task 4, 2e→Task 6, 2f→Task 7, docs→Task 8; Task 1 is the shared model foundation. Stocktwits stretch is deliberately excluded (needs an Actions-runner smoke test first — post-arc).
- Two deliberate deviations from the spec, to be surfaced in review and docs: the `events` component generalizes "8-K hits in 24h" to fresh-alert involvement across all monitors (cheaper, uses existing plumbing, strictly more information); Finnhub is primary-with-fallback rather than an additional feed (avoids doubled network time per ticker).
- run.py accretes wiring from Tasks 2, 4, 5, 6, 7 — tasks are ordered so each merges independently; the sources-dict lines will conflict trivially across parallel tasks (union resolution at merge is expected).
- The EFTS date-bounding and Finnhub fixture steps have explicit adapt-to-reality instructions — live endpoints are ground truth, not this document.
