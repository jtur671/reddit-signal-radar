# E1 Catalyst Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach the radar to see dilution, activist-stake and delisting SEC filings, and fix the composite component those filings would otherwise corrupt.

**Architecture:** Three independent changes, in dependency order. (1) Every monitor declares a `direction` (`bullish`/`bearish`/`neutral`) which is persisted into its self-describing alert file; the composite's `events` component becomes a signed 0/50/100 score that is `None` when no fresh alert covers the ticker. (2) The EDGAR full-text monitor dedups on accession number instead of `accession:filename`, because EFTS indexes every file in a submission separately. (3) That monitor is form-parameterized so the existing 8-K tripwire and four new classes are all config rows.

**Tech Stack:** Python 3.11, pytest, PyYAML, `urllib` (no new dependencies). EDGAR full-text search (`efts.sec.gov`), free, UA-header etiquette.

**Spec:** `docs/superpowers/specs/2026-08-17-catalyst-layer-design.md`

## Global Constraints

- **Run tests with the project venv:** `source .venv/bin/activate` first. Bare `python` is not on PATH. Baseline is **327 passing**; the suite must be green at every commit.
- **No new dependencies.** `requirements.txt` is unchanged by this plan.
- **Monitors must never raise.** `run_fleet` has no `try/except` around `fetch_new` — one bad monitor kills all of the fleet. Parsing helpers are pure and return empty on malformed input.
- **`config.py:6` `_ns()` only recurses into dicts.** A YAML list of dicts arrives as a **list of plain `dict`s**, not `SimpleNamespace`. Use `row["key"]`, never `row.key`.
- **Alert files are self-describing** (`base.py:52`) so the dashboard renders new monitors with no render-code change. Any new field must be written there, not hardcoded in the renderer.
- **Fail-soft with `getattr` defaults**, matching `base.py`'s existing `getattr(monitor, "max_age_h", 48)` / `getattr(m, "seen_cap", 200)` style.
- **EDGAR user agent must carry a contact**, per SEC etiquette. Reuse the configured value; never hardcode.
- Every commit message ends with:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

---

### Task 1: Monitors declare a direction, and alerts persist it

**Files:**
- Modify: `radar/monitors/base.py:23-45` (Monitor protocol), `radar/monitors/base.py:52-61` (`write_alert`)
- Modify: `radar/monitors/__init__.py:19-45` (add `direction` to the five existing monitors)
- Modify: `radar/monitors/prose.py`, `radar/monitors/edgar.py`, `radar/monitors/events.py`, `radar/monitors/congress.py`, `radar/monitors/edgar_events.py` (accept/set `direction`)
- Modify: `radar/run.py:389-415` (`_load_alerts` surfaces `direction`)
- Test: `tests/test_monitors_registry.py`, `tests/test_today_read.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `Monitor.direction: str` — one of `"bullish"`, `"bearish"`, `"neutral"`. Read everywhere via `getattr(m, "direction", "neutral")`.
  - `write_alert()` writes a `"direction"` key into `data/<key>_alert.json`.
  - `_load_alerts()` view-model dicts gain a `direction` key, defaulting to `"neutral"` for legacy alert files that predate this field.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_monitors_registry.py`:

```python
def test_every_registered_monitor_declares_a_valid_direction():
    from radar.config import load_config
    from radar.monitors import build_registry
    cfg = load_config("config.yaml")
    for m in build_registry(cfg):
        d = getattr(m, "direction", None)
        assert d in {"bullish", "bearish", "neutral"}, f"{m.key} has direction={d!r}"


def test_insider_buy_is_bullish_and_the_rest_are_neutral():
    from radar.config import load_config
    from radar.monitors import build_registry
    cfg = load_config("config.yaml")
    by_key = {m.key: m.direction for m in build_registry(cfg)}
    assert by_key["edgar"] == "bullish"          # open-market insider purchase
    # congress lags the trade by up to 45 days -> not fresh bullish news
    for key in ("trump", "fed", "congress", "edgar8k"):
        assert by_key[key] == "neutral"


def test_write_alert_persists_direction(tmp_path):
    from radar.monitors.base import write_alert, Signal
    import json, types
    mon = types.SimpleNamespace(key="k", label="L", card_style="insider",
                                max_age_h=24, direction="bearish")
    sig = Signal(tickers=["AAA"], summary="s", url="u",
                 published="2026-08-17T00:00:00Z", monitor_key="k")
    write_alert(mon, sig, "2026-08-17T01:00:00Z", data_dir=str(tmp_path))
    written = json.loads((tmp_path / "k_alert.json").read_text())
    assert written["direction"] == "bearish"


def test_write_alert_defaults_direction_to_neutral(tmp_path):
    from radar.monitors.base import write_alert, Signal
    import json, types
    mon = types.SimpleNamespace(key="k", label="L", card_style="trump", max_age_h=24)
    sig = Signal(tickers=["AAA"], summary="s", url="u",
                 published="2026-08-17T00:00:00Z", monitor_key="k")
    write_alert(mon, sig, "2026-08-17T01:00:00Z", data_dir=str(tmp_path))
    assert json.loads((tmp_path / "k_alert.json").read_text())["direction"] == "neutral"
```

Add to `tests/test_today_read.py`:

```python
def test_load_alerts_surfaces_direction_and_defaults_legacy_to_neutral(tmp_path):
    # The five alert files live on the data branch today WITHOUT a direction key.
    # They must load as neutral rather than crashing or scoring as good news.
    import json
    from radar.run import _load_alerts
    fresh = "2026-08-17T12:00:00Z"
    (tmp_path / "new_alert.json").write_text(json.dumps(
        {"monitor_key": "new", "label": "L", "card_style": "insider", "tickers": ["AAA"],
         "summary": "s", "url": "u", "published": fresh, "detected_at": fresh,
         "max_age_h": 100000, "direction": "bearish"}))
    (tmp_path / "legacy_alert.json").write_text(json.dumps(
        {"monitor_key": "legacy", "label": "L", "card_style": "trump", "tickers": ["BBB"],
         "summary": "s", "url": "u", "published": fresh, "detected_at": fresh,
         "max_age_h": 100000}))
    by_key = {a["theme_attr"].lower(): a for a in _load_alerts(str(tmp_path))}
    assert by_key["new"]["direction"] == "bearish"
    assert by_key["legacy"]["direction"] == "neutral"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source .venv/bin/activate
python -m pytest tests/test_monitors_registry.py tests/test_today_read.py -v -k "direction"
```

Expected: FAIL — `AttributeError`/`KeyError` on `direction`.

- [ ] **Step 3: Add `direction` to the protocol and `write_alert`**

In `radar/monitors/base.py`, add to the `Monitor` Protocol body (after `max_age_h`):

```python
    direction: str               # "bullish" | "bearish" | "neutral" — signs composite `events`
```

In `write_alert`, add one field to the `dict(...)` call:

```python
        max_age_h=getattr(monitor, "max_age_h", 48),
        direction=getattr(monitor, "direction", "neutral"),
```

- [ ] **Step 4: Give every monitor a direction**

Each monitor class sets `self.direction` alongside `self.key`/`self.label`/`self.card_style`. For the four classes that take it as a constructor argument (`ProseMonitor`, `EdgarMonitor`, `RssEventMonitor`, `CongressMonitor`), add a keyword argument `direction: str = "neutral"` and assign `self.direction = direction`. For `EdgarEventsMonitor` (`radar/monitors/edgar_events.py:86`), set it inline:

```python
        self.key, self.label, self.card_style = "edgar8k", "📢 8-K Event", "insider"
        self.direction = "neutral"
```

Then in `radar/monitors/__init__.py`, pass `direction="bullish"` to the `EdgarMonitor(...)` call only. The other three keep the `"neutral"` default — do not pass the argument, so the default is exercised.

- [ ] **Step 5: Surface `direction` in `_load_alerts`**

In `radar/run.py`, inside the `out.append(dict(...))` block (around line 403), add:

```python
            direction=raw.get("direction") or "neutral",   # legacy alert files predate this
```

- [ ] **Step 6: Run the full suite**

```bash
source .venv/bin/activate && python -m pytest
```

Expected: PASS, 327 + 5 = **332 passed**.

- [ ] **Step 7: Commit**

```bash
git add radar/monitors/ radar/run.py tests/test_monitors_registry.py tests/test_today_read.py
git commit -m "feat(monitors): every monitor declares a bullish/bearish/neutral direction

Persisted into the self-describing alert file so consumers need no registry.
Insider buys are bullish; congress is neutral because disclosure lags the trade
by up to 45 days. Legacy alert files with no direction key load as neutral.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Sign the `events` composite component

**Files:**
- Modify: `radar/composite.py:1-14` (docstring), `radar/composite.py:33-46` (`components_for`)
- Modify: `radar/run.py:153-161` (build ticker→direction map)
- Test: `tests/test_composite.py`

**Interfaces:**
- Consumes: `_load_alerts()` view-models carrying `direction` (Task 1).
- Produces:
  - `radar.composite.EVENT_DIRECTION: dict[str, float]` = `{"bearish": 0.0, "neutral": 50.0, "bullish": 100.0}`
  - `components_for(s, board, ts_bull, alert_direction)` — **fourth parameter renamed and retyped** from `alert_tickers: set[str]` to `alert_direction: dict[str, str]` (ticker → direction).
  - `radar.run.alert_direction_map(alerts) -> dict[str, str]` — flattens `_load_alerts()` output to ticker → most-negative direction.

- [ ] **Step 1: Write the failing tests**

Replace the three existing `components_for(..., alert_tickers=...)` call sites in `tests/test_composite.py` with the new keyword, and add the new cases:

```python
from radar.composite import (blend, components_for, percentile_rank, CRAMER_INVERSE,
                             EVENT_DIRECTION)
from radar.run import alert_direction_map


def test_event_direction_mapping():
    assert EVENT_DIRECTION == {"bearish": 0.0, "neutral": 50.0, "bullish": 100.0}


def test_events_is_signed_by_direction():
    from radar.models import Signal
    s = Signal(ticker="AAA", score=50.0, mentions=10)
    for direction, expected in (("bullish", 100.0), ("neutral", 50.0), ("bearish", 0.0)):
        comps = components_for(s, [s], ts_bull=None, alert_direction={"AAA": direction})
        assert comps["events"] == expected, direction


def test_events_is_none_when_no_fresh_alert():
    # The bug this fixes: a real 0.0 punished every quiet ticker. On the live
    # 2026-08-17 board this component was 0.0 for all 15 rows -- zero variance
    # across 10% of the composite weight.
    from radar.models import Signal
    s = Signal(ticker="AAA", score=50.0, mentions=10)
    assert components_for(s, [s], ts_bull=None, alert_direction={})["events"] is None
    assert components_for(s, [s], ts_bull=None,
                          alert_direction={"OTHER": "bullish"})["events"] is None


def test_events_none_is_dropped_and_weight_renormalized():
    from radar.models import Signal
    s = Signal(ticker="AAA", score=50.0, mentions=10)
    comps = components_for(s, [s], ts_bull=None, alert_direction={})
    _score, used = blend(comps, {"velocity": 0.30, "direction": 0.15, "engagement": 0.10,
                                 "short_pressure": 0.15, "options": 0.10, "events": 0.10,
                                 "cramer_inverse": 0.10})
    assert "events" not in used
    assert abs(sum(used.values()) - 1.0) < 1e-9


def test_alert_direction_map_bearish_beats_bullish_beats_neutral():
    # REPL drew a 424B5, an S-3ASR and a SCHEDULE 13D inside one week (2026-08-10..14).
    alerts = [
        {"tickers": "$REPL", "direction": "bullish"},
        {"tickers": "$REPL", "direction": "neutral"},
        {"tickers": "$REPL", "direction": "bearish"},
    ]
    assert alert_direction_map(alerts) == {"REPL": "bearish"}
    assert alert_direction_map(alerts[:2]) == {"REPL": "bullish"}
    assert alert_direction_map(alerts[1:2]) == {"REPL": "neutral"}


def test_alert_direction_map_splits_multi_ticker_and_strips_cashtags():
    alerts = [{"tickers": "$SPY · $TLT · $IWM", "direction": "neutral"}]
    assert alert_direction_map(alerts) == {"SPY": "neutral", "TLT": "neutral", "IWM": "neutral"}
    assert alert_direction_map([{"tickers": "", "direction": "bearish"}]) == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source .venv/bin/activate && python -m pytest tests/test_composite.py -v
```

Expected: FAIL — `ImportError` on `EVENT_DIRECTION` / `alert_direction_map`.

- [ ] **Step 3: Sign the component in `radar/composite.py`**

Add the constant beside `CRAMER_INVERSE`:

```python
EVENT_DIRECTION = {"bearish": 0.0, "neutral": 50.0, "bullish": 100.0}
```

Change the signature and the one line:

```python
def components_for(s, board, ts_bull, alert_direction) -> dict:
```

```python
        "events": EVENT_DIRECTION.get(alert_direction.get(s.ticker)),
```

`dict.get` returns `None` for a ticker with no fresh alert, and `blend()` already drops `None` components and renormalizes — no other change needed.

Update the module docstring's component-semantics line from:

```
events =
fresh monitor-alert involvement (any monitor, 0/100)
```

to:

```
events = signed
fresh-alert direction (bearish 0 / neutral 50 / bullish 100), None when no fresh
alert covers the ticker so a quiet name is not punished with a real zero
```

- [ ] **Step 4: Add `alert_direction_map` to `radar/run.py`**

Add near `_load_alerts` (module level, so tests can import it):

```python
_DIRECTION_RANK = {"bearish": 0, "bullish": 1, "neutral": 2}   # most-negative wins


def alert_direction_map(alerts) -> dict[str, str]:
    """Ticker -> direction across every fresh alert. When one ticker draws several
    alerts the most negative wins: a filed dilution is a harder fact than an
    activist's intentions, and a radar should fail toward warning. Every individual
    alert card still renders — only the blended number is opinionated."""
    out: dict[str, str] = {}
    for a in alerts:
        direction = a.get("direction") or "neutral"
        for raw in (a.get("tickers") or "").split(" · "):
            t = raw.strip().lstrip("$")
            if not t:
                continue
            if t not in out or _DIRECTION_RANK[direction] < _DIRECTION_RANK[out[t]]:
                out[t] = direction
    return out
```

Then replace `radar/run.py:154`:

```python
    alert_tickers = {t.strip("$") for a in alerts for t in a["tickers"].split(" · ") if t}
```

with:

```python
    alert_direction = alert_direction_map(alerts)
```

and update the call at line 160:

```python
        s.components = components_for(s, board, ts_by_bull.get(s.ticker), alert_direction)
```

- [ ] **Step 5: Run the full suite**

```bash
source .venv/bin/activate && python -m pytest
```

Expected: PASS. Fix any other `alert_tickers=` call site the rename surfaces.

- [ ] **Step 6: Verify against the live board**

```bash
source .venv/bin/activate
python3 -m radar.run --dry-run --no-email --out /tmp/e1check
python3 -c "
import json; d=json.load(open('/tmp/e1check/data.json'))
import collections
print('events:', collections.Counter(s['components']['events'] for s in d['signals']))
print('composite:', sorted(s['composite'] for s in d['signals']))"
```

Expected: `events` is now `None` for most/all rows (was `0.0` for all 15), and composites shift **upward** because a constant-zero component no longer drags every score.

- [ ] **Step 7: Commit**

```bash
git add radar/composite.py radar/run.py tests/test_composite.py
git commit -m "fix(composite): sign the events component and drop it when quiet

Two bugs, one change. (1) events was unsigned -- any fresh alert scored 100.0
and run.py discarded monitor identity, so a 424B5 dilution would have RAISED a
ticker's composite. (2) 'no alert' scored a real 0.0, not null: on the live
2026-08-17 board events was 0.0 for all 15 rows, zero variance across 10% of
the weight -- a uniform drag that discriminated nothing.

Now bearish/neutral/bullish -> 0/50/100, and None when no fresh alert covers
the ticker, which blend() already drops and renormalizes. Ties resolve to the
most negative direction.

BACKTEST REGIME BOUNDARY: every composite shifts.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Dedup EDGAR hits by accession number

**Files:**
- Modify: `radar/monitors/edgar_events.py:37-63` (`parse_hits`), `radar/monitors/edgar_events.py:96-114` (`fetch_new`)
- Test: `tests/test_edgar_events.py`

**Interfaces:**
- Consumes: nothing from Tasks 1–2.
- Produces: `parse_hits(raw)` rows whose `id` is the **accession number** (`"0001193125-26-344989"`), not `"<accession>:<filename>"`. `url` is unchanged and still uses the filename.

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_hits_id_is_the_accession_number():
    # EFTS indexes every FILE in a submission separately -- the primary document AND
    # each exhibit. Measured 2026-08-10..14: S-3,S-3ASR returned 100 hits for only 35
    # filings, one filing yielding SIX. Keying on "<accession>:<filename>" would alert
    # once per exhibit. The live 8-K monitor is accidentally immune (ratio exactly 1.0)
    # because "material definitive agreement" appears only in the primary document.
    raw = {"hits": {"hits": [
        {"_id": "0001213900-26-087891:form-s3.htm",
         "_source": {"ciks": ["0000012345"], "display_names": ["Acme  (ACME)  (CIK 1)"],
                     "file_date": "2026-08-12"}},
        {"_id": "0001213900-26-087891:ex-5_1.htm",
         "_source": {"ciks": ["0000012345"], "display_names": ["Acme  (ACME)  (CIK 1)"],
                     "file_date": "2026-08-12"}},
    ]}}
    rows = parse_hits(raw)
    assert [r["id"] for r in rows] == ["0001213900-26-087891"] * 2
    assert rows[0]["url"].endswith("form-s3.htm")     # url still needs the filename


def test_fetch_new_emits_one_signal_per_filing(monkeypatch):
    import radar.monitors.edgar_events as ee
    six_files = {"hits": {"hits": [
        {"_id": f"acc1:ex-{i}.htm",
         "_source": {"ciks": ["1"], "display_names": ["Watched Co  (WTCH)  (CIK 1)"],
                     "file_date": "2026-08-12"}} for i in range(6)]}}
    monkeypatch.setattr(ee, "_fetch_json", lambda url, ua: six_files)
    m = EdgarEventsMonitor(phrases=["offering"], user_agent="t", watch=lambda: {"WTCH"})
    signals, evaluated = m.fetch_new(set())
    assert len(signals) == 1                      # six files, one filing, one alert
    assert evaluated == ["acc1"]


def test_fetch_new_honours_a_legacy_accession_colon_filename_cursor(monkeypatch):
    # data/edgar8k_seen.json holds "<accession>:<filename>" entries written before this
    # change. Without normalisation the first tick after deploy re-alerts on filings
    # already seen.
    import radar.monitors.edgar_events as ee
    fixture = {"hits": {"hits": [
        {"_id": "acc1:doc.htm",
         "_source": {"ciks": ["1"], "display_names": ["Watched Co  (WTCH)  (CIK 1)"],
                     "file_date": "2026-08-12"}}]}}
    monkeypatch.setattr(ee, "_fetch_json", lambda url, ua: fixture)
    m = EdgarEventsMonitor(phrases=["x"], user_agent="t", watch=lambda: {"WTCH"})
    signals, _ = m.fetch_new({"acc1:some-other-file.htm"})
    assert signals == []
```

Update the existing `test_monitor_filters_to_watchset_and_advances_cursor` assertions to the new ids:

```python
    assert set(evaluated) == {"acc1", "acc2"}       # non-hits advance the cursor too
    signals2, _ = m.fetch_new({"acc1", "acc2"})
    assert signals2 == []                            # dedup works
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source .venv/bin/activate && python -m pytest tests/test_edgar_events.py -v
```

Expected: FAIL — ids are still `"acc1:doc.htm"`.

- [ ] **Step 3: Make the accession the id**

In `parse_hits`, the `acc_no`/`fname` split already exists at line 50. Change only the row's `id`:

```python
        out.append({
            "id": acc_no,                    # accession, NOT acc_no:fname -- EFTS indexes
                                             # every file in a submission separately
            "ticker": ticker_from_display(display),
            "display": display,
            "file_date": str(src.get("file_date") or ""),
            "url": url,
        })
```

- [ ] **Step 4: Normalize the incoming cursor in `fetch_new`**

As the first line of `fetch_new`, before the watch lookup:

```python
    def fetch_new(self, seen: set[str]):
        # Cursors written before the accession-dedup change hold "<accession>:<filename>".
        # Normalise so the first tick after deploy does not re-alert on seen filings.
        seen = {str(s).partition(":")[0] for s in seen}
```

The existing `if row["id"] in seen or row["id"] in evaluated: continue` guard then collapses the six-exhibit case to one signal with no further change.

- [ ] **Step 5: Run the full suite**

```bash
source .venv/bin/activate && python -m pytest
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add radar/monitors/edgar_events.py tests/test_edgar_events.py
git commit -m "fix(edgar): dedup filings by accession, not accession:filename

EFTS indexes every FILE in a submission separately -- the primary document and
each exhibit. Measured 2026-08-10..14: S-3,S-3ASR returned 100 hits for only 35
filings, worst case one filing yielding six. The live 8-K monitor never exposed
this because 'material definitive agreement' appears only in the primary
document (ratio exactly 1.0), but 'offering' also matches the underwriting
agreement, legal opinion and fee exhibits.

Normalises legacy cursors so the first tick after deploy does not re-alert.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Form-parameterize the EDGAR monitor

**Files:**
- Modify: `radar/monitors/edgar_events.py:1-5` (docstring), `:17-18` (`EFTS`), `:66-79` (`active_tickers`), `:82-114` (class)
- Test: `tests/test_edgar_events.py`

**Interfaces:**
- Consumes: accession ids from Task 3, `direction` from Task 1.
- Produces: `EdgarEventsMonitor(phrases, user_agent, watch=active_tickers, max_age_h=24, key="edgar8k", label="📢 8-K Event", card_style="insider", direction="neutral", forms="8-K", watch_days=7)` — every new parameter is keyword-only with a default that reproduces today's 8-K behaviour exactly.

- [ ] **Step 1: Write the failing tests**

```python
def test_efts_url_carries_configured_forms_and_phrase(monkeypatch):
    import radar.monitors.edgar_events as ee
    seen_urls = []
    def fake(url, ua):
        seen_urls.append(url)
        return {"hits": {"hits": []}}
    monkeypatch.setattr(ee, "_fetch_json", fake)
    m = EdgarEventsMonitor(phrases=["at the market offering"], user_agent="t",
                           watch=lambda: set(), key="dilution", forms="424B5")
    m.fetch_new(set())
    assert "forms=424B5" in seen_urls[0]
    assert "at%20the%20market%20offering" in seen_urls[0]


def test_comma_separated_forms_are_url_encoded(monkeypatch):
    # forms= accepts several codes; S-3,S-3ASR is additive (verified 2026-08-17).
    import radar.monitors.edgar_events as ee
    seen_urls = []
    monkeypatch.setattr(ee, "_fetch_json",
                        lambda url, ua: (seen_urls.append(url), {"hits": {"hits": []}})[1])
    m = EdgarEventsMonitor(phrases=["offering"], user_agent="t", watch=lambda: set(),
                           key="shelf", forms="S-3,S-3ASR")
    m.fetch_new(set())
    assert "forms=S-3%2CS-3ASR" in seen_urls[0] or "forms=S-3,S-3ASR" in seen_urls[0]


def test_defaults_reproduce_todays_8k_monitor(monkeypatch):
    import radar.monitors.edgar_events as ee
    seen_urls = []
    monkeypatch.setattr(ee, "_fetch_json",
                        lambda url, ua: (seen_urls.append(url), {"hits": {"hits": []}})[1])
    m = EdgarEventsMonitor(phrases=["material definitive agreement"], user_agent="t",
                           watch=lambda: set())
    m.fetch_new(set())
    assert m.key == "edgar8k" and m.label == "📢 8-K Event"
    assert m.card_style == "insider" and m.direction == "neutral"
    assert m.watch_days == 7 and "forms=8-K" in seen_urls[0]


def test_identity_fields_are_configurable():
    m = EdgarEventsMonitor(phrases=["x"], user_agent="t", watch=lambda: set(),
                           key="dilution", label="💧 Dilution", card_style="trump",
                           direction="bearish", forms="424B5", watch_days=90)
    assert (m.key, m.label, m.card_style, m.direction) == (
        "dilution", "💧 Dilution", "trump", "bearish")


def test_watch_days_is_passed_to_the_default_watch(tmp_path, monkeypatch):
    import json
    import radar.monitors.edgar_events as ee
    hist = tmp_path / "history.json"
    hist.write_text(json.dumps({
        "RECENT": {"2026-08-16": {"raw": 5}},
        "OLD":    {"2026-06-20": {"raw": 5}}}))
    narrow = ee.active_tickers(str(hist), days=7,  today="2026-08-17")
    wide   = ee.active_tickers(str(hist), days=90, today="2026-08-17")
    assert narrow == {"RECENT"}
    assert wide == {"RECENT", "OLD"}       # the 90-day gate is what catches pre-discovery names
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source .venv/bin/activate && python -m pytest tests/test_edgar_events.py -v
```

Expected: FAIL — `TypeError: unexpected keyword argument 'forms'`.

- [ ] **Step 3: Parameterize the URL template**

Replace the `EFTS` constant:

```python
EFTS = ("https://efts.sec.gov/LATEST/search-index?q={q}&forms={forms}"
        "&dateRange=custom&startdt={start}&enddt={end}")
```

- [ ] **Step 4: Parameterize the constructor**

Replace `EdgarEventsMonitor.__init__` with:

```python
    def __init__(self, phrases: list[str], user_agent: str,
                 watch=active_tickers, max_age_h: int = 24, *,
                 key: str = "edgar8k", label: str = "📢 8-K Event",
                 card_style: str = "insider", direction: str = "neutral",
                 forms: str = "8-K", watch_days: int = 7):
        self.key, self.label, self.card_style = key, label, card_style
        self.direction = direction
        self.max_age_h = max_age_h
        self.phrases = list(phrases)
        self.forms = forms
        self.watch_days = watch_days
        self.user_agent = user_agent
        self._watch = watch
        # Three phrases over the rolling window can exceed the base.py default seen_cap
        # of 200 (one phrase alone returned 72 in-window ids) -> evicted ids re-evaluate
        # every tick (cursor churn + duplicate alerts). Match EdgarMonitor's 5000.
        self.seen_cap = 5000
```

- [ ] **Step 5: Use `forms` and `watch_days` in `fetch_new`**

The watch call must pass `watch_days` when the callable accepts it, while still supporting the `lambda: set()` used throughout the tests:

```python
        try:
            watch = self._watch(days=self.watch_days) if callable(self._watch) else set(self._watch)
        except TypeError:
            watch = self._watch() if callable(self._watch) else set(self._watch)
```

And in the fetch loop, pass the form code through:

```python
            raw = _fetch_json(
                EFTS.format(q=q, forms=urllib.parse.quote(self.forms, safe=""),
                            start=start, end=end),
                self.user_agent)
```

Also add the page-cap warning required by the spec, immediately after the `_fetch_json` call:

```python
            hits = parse_hits(raw)
            if len(hits) >= 100:        # EFTS caps a page at 100; we read page 1 only
                degrade.warn(f"{self.key}: EFTS returned a full page for "
                             f"{self.forms}/{phrase!r} — filings are being dropped")
            for row in hits:
```

with `from radar import degrade` added to the imports.

- [ ] **Step 6: Update the module docstring**

```python
"""EDGAR full-text tripwire (structured). Searches efts.sec.gov (free, UA-header
etiquette) for a configured phrase within a configured form class, filed in the last
day, and alerts when the filer maps to a ticker the radar tracks. One instance per form
class: 8-K material events, 424B5 dilution, S-3 shelves, SCHEDULE 13D activist stakes,
25-NSE delistings. Date-bounds every query — the unbounded endpoint returns decade-old
filings — and dedups on the accession number, because EFTS indexes every file in a
submission separately."""
```

- [ ] **Step 7: Run the full suite**

```bash
source .venv/bin/activate && python -m pytest
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add radar/monitors/edgar_events.py tests/test_edgar_events.py
git commit -m "refactor(edgar): form-parameterize the EDGAR full-text monitor

forms=, the identity fields and the watch-gate width all become constructor
arguments, every default reproducing today's 8-K behaviour exactly. Adds a
DEGRADED warning when EFTS returns a full 100-hit page, since parse_hits reads
page 1 only -- the live 8-K query already sits near that cap (~87 for one of
three phrases over its 2-day window).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Wire the four catalyst classes into config and the registry

**Files:**
- Modify: `config.yaml` (add `edgar_forms`, after the `edgar_events` block)
- Modify: `radar/monitors/__init__.py:14-45` (`build_registry`)
- Test: `tests/test_monitors_registry.py`

**Interfaces:**
- Consumes: `EdgarEventsMonitor` keyword arguments (Task 4), `direction` (Task 1).
- Produces: a registry of **nine** monitors — the five existing plus `dilution`, `shelf`, `activist`, `delisting`.

- [ ] **Step 1: Write the failing tests**

```python
def test_registry_includes_the_four_catalyst_classes():
    from radar.config import load_config
    from radar.monitors import build_registry
    by_key = {m.key: m for m in build_registry(load_config("config.yaml"))}
    assert {"dilution", "shelf", "activist", "delisting"} <= set(by_key)
    assert len(by_key) == 9                       # 5 existing + 4 new, all keys distinct


def test_catalyst_classes_carry_the_measured_form_codes_and_phrases():
    from radar.config import load_config
    from radar.monitors import build_registry
    by_key = {m.key: m for m in build_registry(load_config("config.yaml"))}
    # The q phrase is the debt/equity discriminator: with q="offering", 424B5 hits are
    # dominated by investment-grade BOND takedowns (AMD, IBM, UPS). Measured 2026-08-17.
    assert by_key["dilution"].forms == "424B5"
    assert by_key["dilution"].phrases == ["at the market offering"]
    assert by_key["dilution"].direction == "bearish"
    assert by_key["shelf"].forms == "S-3,S-3ASR"
    assert by_key["shelf"].direction == "neutral"
    # "SCHEDULE 13D", NOT "SC 13D" -- the latter returns zero hits.
    assert by_key["activist"].forms == "SCHEDULE 13D"
    assert by_key["activist"].direction == "bullish"
    assert by_key["delisting"].forms == "25-NSE"
    assert by_key["delisting"].direction == "bearish"


def test_catalyst_classes_watch_90_days_and_edgar8k_still_watches_7():
    from radar.config import load_config
    from radar.monitors import build_registry
    by_key = {m.key: m for m in build_registry(load_config("config.yaml"))}
    for key in ("dilution", "shelf", "activist", "delisting"):
        assert by_key[key].watch_days == 90, key
    assert by_key["edgar8k"].watch_days == 7      # unchanged: widening it is a separate call
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source .venv/bin/activate && python -m pytest tests/test_monitors_registry.py -v
```

Expected: FAIL — keys missing from the registry.

- [ ] **Step 3: Add the config block**

Append to `config.yaml`, directly after the `edgar_events:` block:

```yaml
# Catalyst tripwires (E1): one EDGAR full-text monitor per form class. The `phrases`
# entry is the debt/equity discriminator, not a market-cap filter — with q="offering"
# the 424B5 hits are dominated by investment-grade BOND shelf takedowns (AMD, IBM, UPS);
# "at the market offering" returns only small/mid-cap equity ATMs (measured 2026-08-17).
# Form code is "SCHEDULE 13D", not "SC 13D" (the latter returns zero hits).
# Deliberately excluded: SCHEDULE 13G (~1,300/5d, passive) and NT 10-Q (~96/6d) —
# volume, not signal. watch_days: 90 covers the full history (654 tickers) so a filing
# on a name Reddit is ABOUT to discover still fires; edgar8k keeps its own 7-day gate.
edgar_forms:
  - {key: dilution,  label: "💧 Dilution",      direction: bearish, card_style: dilution,
     forms: "424B5",          phrases: ["at the market offering"], watch_days: 90, max_age_h: 24}
  - {key: shelf,     label: "📄 Shelf Filed",   direction: neutral, card_style: fed,
     forms: "S-3,S-3ASR",     phrases: ["offering"],               watch_days: 90, max_age_h: 24}
  - {key: activist,  label: "🎯 Activist 13D",  direction: bullish, card_style: insider,
     forms: "SCHEDULE 13D",   phrases: ["common stock"],           watch_days: 90, max_age_h: 48}
  - {key: delisting, label: "🚫 Delisting",     direction: bearish, card_style: delisting,
     forms: "25-NSE",         phrases: ["delisting"],              watch_days: 90, max_age_h: 48}
```

`card_style: dilution` and `card_style: delisting` have no CSS rule, so
`dashboard.html.j2:268`'s `class="alert alert-{{ a.style }}"` falls through to the base
`.alert` rule — which is already red (`--down`). That is the intended bearish look with
no template change.

- [ ] **Step 4: Build them in the registry**

In `radar/monitors/__init__.py`, inside `build_registry`, after the existing
`EdgarEventsMonitor(...)` entry, extend the returned list:

```python
def build_registry(cfg) -> list:
    ec, fc, cc, ev = cfg.edgar, cfg.fed, cfg.congress, cfg.edgar_events
    monitors = [
        ...                                    # the five existing entries, unchanged
    ]
    # config.py's _ns() only recurses into dicts, so a YAML list arrives as a list of
    # plain dicts -- index with row["key"], never row.key.
    for row in (getattr(cfg, "edgar_forms", None) or []):
        monitors.append(EdgarEventsMonitor(
            phrases=list(row["phrases"]), user_agent=ev.user_agent,
            max_age_h=int(row.get("max_age_h", 24)),
            key=row["key"], label=row["label"], card_style=row["card_style"],
            direction=row["direction"], forms=row["forms"],
            watch_days=int(row.get("watch_days", 90)),
        ))
    return monitors
```

- [ ] **Step 5: Run the full suite**

```bash
source .venv/bin/activate && python -m pytest
```

Expected: PASS.

- [ ] **Step 6: Smoke-test the real fleet against live EDGAR**

```bash
source .venv/bin/activate
git fetch origin data && git checkout origin/data -- data/     # real cursors
python3 -m radar.monitor
git checkout -- data/                                          # discard cursor churn
```

Expected: exits 0, prints `FLEET: …`. Confirm no monitor raised — `run_fleet` has no
`try/except` around `fetch_new`, so a traceback here means one bad class kills all nine.

- [ ] **Step 7: Commit**

```bash
git add config.yaml radar/monitors/__init__.py tests/test_monitors_registry.py
git commit -m "feat(catalyst): four EDGAR form-class tripwires

dilution (424B5), shelf (S-3,S-3ASR), activist (SCHEDULE 13D) and delisting
(25-NSE), each a config row. Watch the full 90-day history (654 tickers) rather
than the 7-day active set (148) so a filing on a name Reddit is about to
discover still fires -- MVIS filed a 424B5 the same week r/pennystocks called it
a squeeze candidate, and is absent from the 7-day gate entirely.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Document the change and stamp the regime boundary

**Files:**
- Modify: `README.md` (Monitor fleet section, Configuration section)
- Modify: `radar/backtest.py` (`regime_notes`)
- Modify: `docs/ROADMAP.md` (tick E1, add decision-log entry), `docs/HANDOFF.md` (tick E1, move to §5)

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: no code interfaces.

- [ ] **Step 1: Add the regime-boundary entry**

`radar/backtest.py:19` holds `REGIME_NOTES`, a list of `{"date", "note"}` dicts.
Prepend the new entry so the list stays newest-first:

```python
REGIME_NOTES = [
    {"date": "2026-08-17",
     "note": "E1 catalyst layer: composite `events` became signed (bearish 0 / "
             "neutral 50 / bullish 100) and None when no fresh alert covers the "
             "ticker, where it was previously 100/0 with 0 for 'no alert'. Every "
             "composite before and after this date is incomparable. Four new alert "
             "classes (dilution/shelf/activist/delisting) also feed `events`."},
    {"date": "2026-08-07",
     "note": "PR #4 merged: history 'state' becomes board-relative for board names; "
             "noise floor min_mentions 5 -> 10."},
]
```

- [ ] **Step 2: Update the README**

In the **Monitor fleet** section, change "runs five tripwire monitors" to "runs nine
tripwire monitors" and add the four classes to the bullet list, each one line, naming
its form code and direction. In the **Configuration** section, add `edgar_forms` to the
list of config blocks. In the composite description near the top, correct the `events`
component's semantics from "fresh-alert involvement" to the signed mapping.

- [ ] **Step 3: Run the full suite one final time**

```bash
source .venv/bin/activate && python -m pytest
```

Expected: PASS.

- [ ] **Step 4: Tick the tracking docs**

In `docs/ROADMAP.md`, check off every E1 box and add a decision-log entry. In
`docs/HANDOFF.md`, check off the E1 block, move it to §5 with the commit SHA, set §1's
phase to E2, and **strike the "Open defect" block in §1** — Task 2 fixed it. Leave the
"measure real alert volume after 1 week" item **unchecked**; it is a future measurement,
and its hook says to record the real number in §4 beside the ~3.2/day estimate.

- [ ] **Step 5: Commit**

```bash
git add README.md radar/backtest.py docs/
git commit -m "docs(catalyst): document the nine-monitor fleet and stamp the regime boundary

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage.** §1.1(a) unsigned → Tasks 1–2. §1.1(b) dead weight → Task 2 (`None` when quiet). §2.1 signed mapping and conflict rule → Task 2. §2.2 form parameterization and the `watch_days` split → Task 4. §2.2.1 accession dedup and cursor migration → Task 3. §2.3 config → Task 5. §2.4 alerting/rendering/ordering → Task 5 (no render change; `card_style` fall-through). §2.5 volume → Task 6's unchecked follow-up. §3 data contract and regime boundary → Task 6. §4 testing → every task. §5 page-cap warning → Task 4 Step 5.

**One deliberate deferral:** the spec's §2.4 salience ordering ("`file_date` descending") is **not** implemented — `parse_hits` preserves EFTS relevance order, and every query is bounded to a 1-day window, so `file_date` is near-constant and sorting would be a no-op. Recorded here rather than silently dropped; revisit only if a class ever widens its window.

**Type consistency.** `alert_direction` is `dict[str, str]` in Tasks 1, 2 and 5. `EVENT_DIRECTION` keys match the three `direction` literals exactly. `parse_hits` row keys (`id`/`ticker`/`display`/`file_date`/`url`) are unchanged except for `id`'s value. `forms`/`watch_days`/`direction` are spelled identically in the config block, the registry loop and the constructor.
