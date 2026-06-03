# Still Running Lane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a separate "Still Running" lane (dashboard + email) that surfaces names which broke out (state `new`/`hot`) in the last 3 days, are still alive today (`sustained`/`hot`), and have dropped off the top-15 board — ranked by `min(velocity, cap) × log10(mentions)`.

**Architecture:** A new pure module `radar/still_running.py` selects and ranks lane names from the already-scored `signals` list using `History`'s per-day `state` records. `run.py` computes the lane after the board, enriches lane names via a shared helper, and threads them into the render context and email. No change to the main board scoring.

**Tech Stack:** Python 3.11, pytest, Jinja2 templates, SimpleNamespace config (`radar/config.py`).

**Spec:** `docs/superpowers/specs/2026-06-03-still-running-lane-design.md`

**Branch:** `feature/still-running-lane` (already exists, spec committed).

---

## File Structure

- **Create** `radar/still_running.py` — pure selection + ranking function. One responsibility: given scored signals + history, return the ranked lane.
- **Create** `tests/test_still_running.py` — unit tests for selection/ranking/edge cases.
- **Modify** `radar/models.py` — add `days_running` field to `Signal`.
- **Modify** `config.yaml` — add `still_running` block. (No `radar/config.py` change needed: it auto-namespaces any YAML keys, and the module reads with `getattr` defaults.)
- **Modify** `radar/run.py` — extract enrichment helper; compute + enrich + thread the lane; extend `_build_context`, `_email_row` path.
- **Modify** `radar/email_report.py` — render a "Still Running" block.
- **Modify** `radar/templates/dashboard.html.j2` — new section 06, bump Archive to 07.
- **Modify** `tests/test_config.py`, `tests/test_render.py`, `tests/test_email.py` — cover the new behavior.

Run all tests with: `cd /Users/jasontur/Desktop/reddit_review && python -m pytest -q`

---

### Task 1: Add `days_running` field to Signal

**Files:**
- Modify: `radar/models.py:48` (end of `Signal` dataclass)

- [ ] **Step 1: Add the field**

In `radar/models.py`, add one line at the end of the `Signal` dataclass (after the `headlines` field on line 48):

```python
    days_running: int | None = None  # Still Running lane: days since the most recent breakout
```

- [ ] **Step 2: Verify nothing broke**

Run: `python -m pytest tests/test_models.py -q`
Expected: PASS (existing model tests unaffected).

- [ ] **Step 3: Commit**

```bash
git add radar/models.py
git commit -m "feat(model): add days_running field to Signal for Still Running lane"
```

---

### Task 2: Add the `still_running` config block

**Files:**
- Modify: `config.yaml` (end of file, before or after `timezone`)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_still_running_config_block():
    c = load_config("config.yaml")
    assert c.still_running.lookback_days == 3
    assert c.still_running.max_items == 5
    assert c.still_running.velocity_cap == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py::test_still_running_config_block -v`
Expected: FAIL with `AttributeError: 'types.SimpleNamespace' object has no attribute 'still_running'`

- [ ] **Step 3: Add the config block**

Append to `config.yaml` (after the `timezone:` line):

```yaml
# Still Running lane: keep recently-broken-out names that have fallen off the top-N board
# visible while they're still elevated.
still_running:
  lookback_days: 3     # broke out (new/hot) within this many prior days
  max_items: 5         # lane size
  velocity_cap: 10     # cap on the elevation multiplier when ranking
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config.yaml tests/test_config.py
git commit -m "feat(config): add still_running lane settings"
```

---

### Task 3: The `still_running` selection + ranking module

**Files:**
- Create: `radar/still_running.py`
- Test: `tests/test_still_running.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_still_running.py`:

```python
from types import SimpleNamespace
from radar.models import Signal
from radar.history import History
from radar.still_running import still_running


def _sig(ticker, state, velocity, mentions):
    s = Signal(ticker=ticker, mentions=mentions, state=state)
    s.velocity = velocity
    return s


def _hist(states_by_ticker):
    """states_by_ticker: {ticker: {day: state}} -> a real History."""
    data = {
        t: {d: {"weighted": 1.0, "raw": 1, "authors": 0,
                "pct_bull": 0, "score": 0, "state": st}
            for d, st in days.items()}
        for t, days in states_by_ticker.items()
    }
    return History("x", data)


def _cfg(lookback=3, max_items=5, cap=10):
    return SimpleNamespace(still_running=SimpleNamespace(
        lookback_days=lookback, max_items=max_items, velocity_cap=cap))


def test_qualifies_broke_out_alive_offboard():
    sig = _sig("MRVL", "sustained", velocity=2.0, mentions=931)
    hist = _hist({"MRVL": {"2026-06-02": "new"}})
    out = still_running([sig], hist, "2026-06-03", board=[], cfg=_cfg())
    assert [s.ticker for s in out] == ["MRVL"]
    assert out[0].days_running == 1


def test_excludes_new_today():
    sig = _sig("FOO", "new", 5.0, 500)
    hist = _hist({"FOO": {"2026-06-02": "new"}})
    assert still_running([sig], hist, "2026-06-03", [], _cfg()) == []


def test_excludes_cooling_today():
    sig = _sig("FOO", "cooling", 0.5, 500)
    hist = _hist({"FOO": {"2026-06-02": "hot"}})
    assert still_running([sig], hist, "2026-06-03", [], _cfg()) == []


def test_excludes_breakout_older_than_lookback():
    sig = _sig("FOO", "sustained", 2.0, 500)
    hist = _hist({"FOO": {"2026-05-30": "new"}})  # 4 days before, lookback 3
    assert still_running([sig], hist, "2026-06-03", [], _cfg(lookback=3)) == []


def test_excludes_on_board():
    sig = _sig("MRVL", "sustained", 2.0, 931)
    hist = _hist({"MRVL": {"2026-06-02": "new"}})
    board = [_sig("MRVL", "sustained", 2.0, 931)]
    assert still_running([sig], hist, "2026-06-03", board, _cfg()) == []


def test_ranking_velocity_times_logvolume_with_cap():
    a = _sig("A", "sustained", 3.0, 100)     # 3 * log10(100)=2 -> 6
    b = _sig("B", "hot", 50.0, 1000)         # min(50,10)=10 * log10(1000)=3 -> 30
    hist = _hist({"A": {"2026-06-02": "new"}, "B": {"2026-06-02": "hot"}})
    out = still_running([a, b], hist, "2026-06-03", [], _cfg(cap=10))
    assert [s.ticker for s in out] == ["B", "A"]


def test_truncates_to_max_items():
    sigs = [_sig(f"T{i}", "sustained", 2.0, 100 + i) for i in range(8)]
    hist = _hist({f"T{i}": {"2026-06-02": "new"} for i in range(8)})
    out = still_running(sigs, hist, "2026-06-03", [], _cfg(max_items=5))
    assert len(out) == 5


def test_empty_when_nothing_qualifies():
    assert still_running([], _hist({}), "2026-06-03", [], _cfg()) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_still_running.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'radar.still_running'`

- [ ] **Step 3: Write the module**

Create `radar/still_running.py`:

```python
from __future__ import annotations
import math
from datetime import date

BREAKOUT_STATES = {"new", "hot"}     # what counts as "it popped"
ALIVE_STATES = {"sustained", "hot"}  # still elevated today (not new, not cooling)


def _breakout_days(history, ticker, run_day, lookback_days):
    """Ordinals of prior days (within the lookback window, excluding run_day) on
    which this ticker's recorded state was new/hot."""
    hist = history.days_for(ticker)
    run_ord = date.fromisoformat(run_day).toordinal()
    cutoff = run_ord - lookback_days
    return [o for d, rec in hist.items()
            for o in (date.fromisoformat(d).toordinal(),)
            if cutoff <= o < run_ord and rec.get("state") in BREAKOUT_STATES]


def _rank_key(s, velocity_cap):
    return min(s.velocity, velocity_cap) * math.log10(max(s.mentions, 10))


def still_running(signals, history, run_day, board, cfg):
    """Names that broke out (new/hot) within the lookback window, are still alive
    today (sustained/hot), and have fallen off the top-N board. Ranked by
    min(velocity, cap) * log10(mentions), truncated to max_items. Each returned
    Signal gets `days_running` = run_day minus its most recent breakout day."""
    sr = getattr(cfg, "still_running", None)
    lookback_days = int(getattr(sr, "lookback_days", 3))
    max_items = int(getattr(sr, "max_items", 5))
    velocity_cap = float(getattr(sr, "velocity_cap", 10))
    run_ord = date.fromisoformat(run_day).toordinal()
    on_board = {s.ticker for s in board}

    out = []
    for s in signals:
        if s.ticker in on_board or s.state not in ALIVE_STATES:
            continue
        days = _breakout_days(history, s.ticker, run_day, lookback_days)
        if not days:
            continue
        s.days_running = run_ord - max(days)   # since the MOST RECENT breakout
        out.append(s)
    out.sort(key=lambda s: _rank_key(s, velocity_cap), reverse=True)
    return out[:max_items]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_still_running.py -q`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add radar/still_running.py tests/test_still_running.py
git commit -m "feat(still-running): selection + ranking module with tests"
```

---

### Task 4: Extract a reusable per-ticker enrichment helper in run.py

This is a pure refactor — no behavior change. It isolates the enrichment loop body so the lane can reuse it.

**Files:**
- Modify: `radar/run.py:42-53`

- [ ] **Step 1: Add the helper function**

In `radar/run.py`, add this function just above `def main(` (after the imports, around line 16):

```python
def _enrich_ticker(s, by_ticker, about_cache, about_ua, themes):
    """Attach themes, engagement, 'what it is', the news catalyst, and a DeepSeek
    summary to one Signal. Shared by the board and the Still Running lane."""
    a = by_ticker.get(s.ticker)
    s.themes = themes.themes_for(s.ticker)
    if a is None:
        return
    s.upvotes = a.upvotes
    s.pct_bull = engagement_pct(a.upvotes, a.mentions)   # engagement proxy (not directional)
    info = about.describe(s.ticker, a.name, about_cache, about_ua)  # 'what is this company'
    s.name, s.about_desc, s.about_extract = info["name"], info["desc"], info["extract"]
    theme = s.themes[0] if s.themes else "stocks"
    s.headlines = news.headlines(s.ticker, a.name, about_ua)   # the catalyst behind the chatter
    s.summary = summarize(s.ticker, s.headlines, theme)        # WHY it's trending, from real news
```

- [ ] **Step 2: Replace the inline loop with a call**

In `main()`, replace the loop body at `radar/run.py:42-53`:

```python
    for s in board:
        a = by_ticker.get(s.ticker)
        s.themes = themes.themes_for(s.ticker)
        if a is None:
            continue
        s.upvotes = a.upvotes
        s.pct_bull = engagement_pct(a.upvotes, a.mentions)   # engagement proxy (not directional)
        info = about.describe(s.ticker, a.name, about_cache, about_ua)  # 'what is this company'
        s.name, s.about_desc, s.about_extract = info["name"], info["desc"], info["extract"]
        theme = s.themes[0] if s.themes else "stocks"
        s.headlines = news.headlines(s.ticker, a.name, about_ua)   # the catalyst behind the chatter
        s.summary = summarize(s.ticker, s.headlines, theme)        # WHY it's trending, from real news
```

with:

```python
    for s in board:
        _enrich_ticker(s, by_ticker, about_cache, about_ua, themes)
```

- [ ] **Step 3: Verify the smoke test still passes**

Run: `python -m pytest tests/test_run_smoke.py -q`
Expected: PASS (behavior unchanged).

- [ ] **Step 4: Commit**

```bash
git add radar/run.py
git commit -m "refactor(run): extract _enrich_ticker helper (no behavior change)"
```

---

### Task 5: Compute, enrich, and thread the lane through run.py

**Files:**
- Modify: `radar/run.py` (main flow + `_build_context`)

- [ ] **Step 1: Import the module**

In `radar/run.py`, add to the imports near the top (after `from radar.score import score_aggregates, top_signals` on line 10):

```python
from radar.still_running import still_running
```

- [ ] **Step 2: Compute the lane and enrich it**

In `main()`, immediately after `board = top_signals(signals, cfg.top_n)` (line 32), add:

```python
    still = still_running(signals, history, run_day, board, cfg)
```

Then, right after the `for s in board: _enrich_ticker(...)` loop (added in Task 4), add:

```python
    for s in still:
        _enrich_ticker(s, by_ticker, about_cache, about_ua, themes)
```

- [ ] **Step 3: Include lane names in price enrichment and the detail blob**

In `radar/run.py`, change `enrich(board)` (line 54) to:

```python
    enrich(board + still)
```

And change the `detail_json` line (`radar/run.py:73`) from:

```python
    detail_json = _detail_blob(board, history, run_day, reddit_subs)
```

to:

```python
    detail_json = _detail_blob(board + still, history, run_day, reddit_subs)
```

- [ ] **Step 4: Pass the lane into the context builder**

In `radar/run.py`, change the `render_html(**_build_context(...))` call (lines 75-77) to add `still`:

```python
    html = render_html(**_build_context(board, signals, run_day, corpus, refreshed,
                                        refreshed_iso, today_read, chips, detail_json, alert,
                                        why_matters, early_plays, still))
```

- [ ] **Step 5: Extend `_build_context` to emit lane rows**

In `radar/run.py`, change the `_build_context` signature (lines 285-287) to accept `still`:

```python
def _build_context(board, signals, run_day, corpus_count, refreshed="", refreshed_iso="",
                   today_read=None, chips=None, detail_json=None, alert=None, why_matters="",
                   early_plays=None, still=None):
```

Then, inside `_build_context`, add `still_running=[...]` to the returned `dict(...)` (insert just before the `themes=(chips or ["All"]),` line, ~line 322):

```python
        still_running=[dict(rank=i+1, ticker=s.ticker, name=s.name, mentions=s.mentions,
                            vel24_disp=_vel24(s)[0], vel24_num=_vel24(s)[1],
                            price=s.price, pct_change=s.pct_change,
                            days_running=(s.days_running or 0),
                            theme=(s.themes[0] if s.themes else ""),
                            themes_attr="|".join(s.themes or []),
                            css=_css(s.state), state_label=s.state.title())
                       for i, s in enumerate(still or [])],
```

- [ ] **Step 6: Verify the smoke test still passes**

Run: `python -m pytest tests/test_run_smoke.py tests/test_render.py -q`
Expected: PASS (existing `_build_context` callers pass `still=None` → empty lane).

- [ ] **Step 7: Commit**

```bash
git add radar/run.py
git commit -m "feat(run): compute, enrich, and thread the Still Running lane"
```

---

### Task 6: Render the dashboard section

**Files:**
- Modify: `radar/templates/dashboard.html.j2` (insert after listings table ~line 290; bump Archive number)
- Test: `tests/test_render.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_render.py`:

```python
def test_still_running_section_renders():
    s = _bsig("MRVL", ["AI Compute"])
    s.days_running = 1; s.price = 308.69; s.pct_change = 6.1; s.name = "Marvell"
    html = render_html(**_build_context([], [s], "2026-06-03", 100, still=[s]))
    assert "Still Running" in html
    assert 'data-ticker="MRVL"' in html
    assert "running 1d" in html


def test_still_running_section_hidden_when_empty():
    s = _bsig("IREN", ["AI Compute"])
    html = render_html(**_build_context([s], [s], "2026-06-03", 100))
    assert "Still Running" not in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_render.py::test_still_running_section_renders -v`
Expected: FAIL (`"Still Running"` not in html — section doesn't exist yet).

- [ ] **Step 3: Insert the template section**

In `radar/templates/dashboard.html.j2`, between the end of the listings `</table>` (line 290) and the `<!-- 05 ARCHIVE -->` comment (line 292), insert:

```jinja
  <!-- 06 STILL RUNNING -->
  {% if still_running %}
  <div class="sec"><span class="no">06</span><span class="nm">Still Running / Proven Movers Holding</span><span class="ln"></span></div>
  {% for r in still_running %}
  <div class="card{% if r.css %} {{ r.css }}{% endif %}" data-themes="{{ r.themes_attr }}" data-ticker="{{ r.ticker }}">
    <div class="hd">
      <span class="rk">№{{ r.rank }}</span><span class="tk">{{ r.ticker }}</span><span class="tag t-sus">running {{ r.days_running }}d</span>
      <div class="px"><div class="v {% if r.pct_change is not none and r.pct_change < 0 %}down{% else %}up{% endif %}">{% if r.price is none %}—{% else %}${{ "%.2f"|format(r.price) }}{% endif %} {% if r.pct_change is none %}{% elif r.pct_change < 0 %}▼{{ "%.1f"|format(r.pct_change|abs) }}%{% else %}▲{{ "%.1f"|format(r.pct_change) }}%{% endif %}</div><div class="th">{{ r.theme }}</div></div>
    </div>
    <div class="row">
      <div class="metric"><div class="mv">{{ r.mentions }}</div><div class="ml">mentions</div></div>
      <div class="metric"><div class="mv {% if r.vel24_num < 1 %}down{% else %}up{% endif %}">{{ r.vel24_disp }}</div><div class="ml">24h velocity</div></div>
    </div>
  </div>
  {% endfor %}
  {% endif %}

```

- [ ] **Step 4: Bump the Archive section number**

In `radar/templates/dashboard.html.j2`, change the Archive section header (line 293) from:

```jinja
  <div class="sec"><span class="no">06</span><span class="nm">Archive &amp; Method</span><span class="ln"></span></div>
```

to:

```jinja
  <div class="sec"><span class="no">07</span><span class="nm">Archive &amp; Method</span><span class="ln"></span></div>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_render.py -q`
Expected: PASS (both new tests + existing render tests).

- [ ] **Step 6: Commit**

```bash
git add radar/templates/dashboard.html.j2 tests/test_render.py
git commit -m "feat(dashboard): render the Still Running section"
```

---

### Task 7: Render the email block and wire it from run.py

**Files:**
- Modify: `radar/email_report.py` (`build_email_html`, `send_email`)
- Modify: `radar/run.py` (email call + a still-row builder)
- Test: `tests/test_email.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_email.py`:

```python
def test_email_includes_still_running_block():
    html = build_email_html(
        "Jun 3",
        [dict(ticker="IREN", velocity=9.4, state="new", pct_bull=78,
              price=14.2, pct_change=8.1, summary="GPU")],
        still=[dict(ticker="MRVL", price=308.69, pct_change=6.1, days_running=1)])
    assert "Still Running" in html
    assert "MRVL" in html
    assert "running 1d" in html


def test_email_no_still_block_when_empty():
    html = build_email_html(
        "Jun 3",
        [dict(ticker="IREN", velocity=9.4, state="new", pct_bull=78,
              price=14.2, pct_change=8.1, summary="GPU")])
    assert "Still Running" not in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_email.py::test_email_includes_still_running_block -v`
Expected: FAIL with `TypeError: build_email_html() got an unexpected keyword argument 'still'`

- [ ] **Step 3: Add the still block to the email builder**

In `radar/email_report.py`, add this helper above `build_email_html` (after the imports, line 2):

```python
def _still_block(still) -> str:
    if not still:
        return ""
    rows = "".join(
        f"<tr><td><b>{_html.escape(s['ticker'])}</b></td>"
        f"<td>{('$%.2f' % s['price']) if s.get('price') is not None else '—'}</td>"
        f"<td>{('%+.1f%%' % s['pct_change']) if s.get('pct_change') is not None else '—'}</td>"
        f"<td>running {int(s.get('days_running') or 0)}d</td></tr>"
        for s in still)
    return f"<h3>Still Running</h3><table cellpadding=6>{rows}</table>"
```

Then change `build_email_html` (lines 4-12) to accept and append `still`:

```python
def build_email_html(date_str: str, signals: list[dict], still: list[dict] | None = None) -> str:
    rows = "".join(
        f"<tr><td><b>{_html.escape(s['ticker'])}</b></td><td>{s['velocity']}×</td>"
        f"<td>{s['pct_bull']}% bull</td><td>{s.get('price') or '—'}</td>"
        f"<td>{_html.escape(str(s.get('summary','')))}</td></tr>"
        for s in signals)
    return (f"<h2>Reddit Signal Radar — {date_str}</h2>"
            f"<table cellpadding=6>{rows}</table>"
            f"{_still_block(still)}"
            f"<p style='color:#888'>Not investment advice.</p>")
```

- [ ] **Step 4: Thread `still` through `send_email`**

In `radar/email_report.py`, change `send_email` (lines 26-27) to:

```python
def send_email(date_str: str, signals: list[dict], still: list[dict] | None = None) -> bool:
    return _send(f"📡 Signal Radar — {date_str}", build_email_html(date_str, signals, still))
```

- [ ] **Step 5: Build still email rows in run.py and pass them**

In `radar/run.py`, add a row builder next to `_email_row` (after line 131):

```python
def _still_email_row(s):
    return dict(ticker=s.ticker, price=s.price, pct_change=s.pct_change,
                days_running=(s.days_running or 0))
```

Then change the `send_email(...)` call (line 82) from:

```python
            send_email(run_day, [_email_row(s) for s in board[:cfg.top_n]])
```

to:

```python
            send_email(run_day, [_email_row(s) for s in board[:cfg.top_n]],
                       [_still_email_row(s) for s in still])
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_email.py -q`
Expected: PASS (both new tests + existing).

- [ ] **Step 7: Commit**

```bash
git add radar/email_report.py radar/run.py tests/test_email.py
git commit -m "feat(email): add Still Running block to the daily email"
```

---

### Task 8: Full-suite integration check

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `python -m pytest -q`
Expected: PASS (all tests, including `test_run_smoke`, `test_invariants`, and the new lane/render/email/config tests).

- [ ] **Step 2: Generate the dashboard locally and eyeball the section**

Run: `python -m radar.run --no-email --dry-run --out /tmp/sr-out`
Expected: exit 0. Then check the section is present (it will only appear if a qualifying name exists in live data; absence is valid):

Run: `grep -c "Still Running" /tmp/sr-out/index.html || echo "lane empty today (valid)"`
Expected: `1` if a name qualifies, otherwise the "lane empty today (valid)" message — both are acceptable.

- [ ] **Step 3: Final commit (if any uncommitted changes remain)**

```bash
git status --short
git add -A && git commit -m "chore(still-running): integration verification" || echo "nothing to commit"
```

---

## Self-Review Notes

**Spec coverage:**
- Inclusion rule (alive today / broke out in lookback / off board) → Task 3 module + tests.
- Ranking `min(velocity, cap) × log10(mentions)`, truncate `max_items` → Task 3 (`_rank_key`, sort, slice) + ranking/truncation tests.
- Enrichment of ≤5 extra names via shared helper → Task 4 (`_enrich_ticker`) + Task 5 (`enrich(board + still)`, detail blob).
- Config block with defaults → Task 2; module reads via `getattr` defaults (Task 3) so test stubs without the block still work.
- Dashboard section, hidden when empty, with price/%/running-Nd → Task 6 + tests.
- Email block, omitted when empty → Task 7 + tests.
- "running N days" = days since most recent breakout → Task 3 (`run_ord - max(days)`), asserted in `test_qualifies_broke_out_alive_offboard`.
- `days_running` field on Signal → Task 1.

**Type consistency:** `still_running(signals, history, run_day, board, cfg)` signature is identical in the module (Task 3), the import + call in run.py (Task 5). Context key `still_running` (Task 5) matches the template `{% if still_running %}` / `{% for r in still_running %}` (Task 6). `_build_context(..., still=None)` param (Task 5) matches the `still=[s]` test calls (Task 6) and the positional `still` arg from `main()` (Task 5 Step 4). `build_email_html(date_str, signals, still=None)` (Task 7) matches the `still=...` test calls and the `send_email` pass-through.

**No placeholders:** every code step shows complete code; every test step shows the assertion; every run step shows the command + expected result.
