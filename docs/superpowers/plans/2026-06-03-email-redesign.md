# Email Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two bare-table radar emails with branded, light/clean, Gmail-safe HTML — the daily digest leads with top-3 mover cards, the Trump alert uses ticker chips + a quoted post.

**Architecture:** Rewrite `radar/email_report.py` around a shared `_shell()` layout plus small render helpers (`_pct`, `_money`, `_button`, `_section`, `_mover_card`, `_rest_table`, `_still_block`). Both `build_*` function signatures stay identical, so `run.py`/`monitor.py` callers are unaffected except for two extra dict fields the cards display.

**Tech Stack:** Python 3.11, pytest, inline-CSS table-based HTML email (no JS, no web fonts).

**Spec:** `docs/superpowers/specs/2026-06-03-email-redesign-design.md`
**Branch:** `feature/email-redesign` (exists; spec committed; a `monitor.py` logging fix is staged/uncommitted).

Run tests with: `cd /Users/jasontur/Desktop/reddit_review && .venv/bin/python -m pytest -q`

---

## File Structure

- **Modify** `radar/monitor.py` — already edited (logging fix); just commit (Task 1).
- **Modify** `radar/run.py` — `_email_row` gains `mentions`+`name`; `_still_email_row` gains `name`+`mentions` (Task 2).
- **Modify** `tests/test_email.py` — keep existing assertions, add card/chip/button/escape/empty tests (Task 3).
- **Rewrite** `radar/email_report.py` — helpers + both build functions; `_send`/`send_email`/`send_trump_alert` keep their behavior (Task 4).

---

### Task 1: Commit the staged monitor.py logging fix

**Files:**
- Modify: `radar/monitor.py` (already edited in the working tree)

- [ ] **Step 1: Confirm the change is present and imports**

Run: `cd /Users/jasontur/Desktop/reddit_review && git diff --stat radar/monitor.py && .venv/bin/python -c "import radar.monitor; print('ok')"`
Expected: shows `radar/monitor.py` modified, prints `ok`.

- [ ] **Step 2: Confirm the trump tests still pass**

Run: `.venv/bin/python -m pytest tests/test_trump.py -q`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add radar/monitor.py
git commit -m "fix(monitor): surface trump-alert email failures in logs instead of swallowing"
```

---

### Task 2: Add card fields to the run.py row builders

**Files:**
- Modify: `radar/run.py` (`_email_row`, `_still_email_row`)

- [ ] **Step 1: Update `_email_row`**

In `radar/run.py`, replace the existing `_email_row`:

```python
def _email_row(s):
    return dict(ticker=s.ticker, velocity=_vel24(s)[0], state=s.state,
                pct_bull=s.pct_bull, price=s.price, pct_change=s.pct_change, summary=s.summary)
```

with (adds `mentions`, `name`):

```python
def _email_row(s):
    return dict(ticker=s.ticker, velocity=_vel24(s)[0], state=s.state,
                pct_bull=s.pct_bull, price=s.price, pct_change=s.pct_change,
                summary=s.summary, mentions=s.mentions, name=s.name)
```

- [ ] **Step 2: Update `_still_email_row`**

In `radar/run.py`, replace the existing `_still_email_row`:

```python
def _still_email_row(s):
    return dict(ticker=s.ticker, price=s.price, pct_change=s.pct_change,
                days_running=(s.days_running or 0))
```

with (adds `name`, `mentions`):

```python
def _still_email_row(s):
    return dict(ticker=s.ticker, price=s.price, pct_change=s.pct_change,
                days_running=(s.days_running or 0), name=s.name, mentions=s.mentions)
```

- [ ] **Step 3: Verify the smoke test still passes**

Run: `.venv/bin/python -m pytest tests/test_run_smoke.py -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add radar/run.py
git commit -m "feat(run): pass mentions+name to email rows for the redesigned cards"
```

---

### Task 3: Write the email tests (TDD — these fail first)

**Files:**
- Modify: `tests/test_email.py` (replace entire file)

- [ ] **Step 1: Replace `tests/test_email.py` with this content**

```python
from radar.email_report import (
    build_email_html, build_trump_alert_email, _pct, _money, DASHBOARD_URL, DIM, UP, DOWN,
)


def _sig(**k):
    base = dict(ticker="IREN", velocity="9.4×", state="new", pct_bull=78,
                price=14.2, pct_change=8.1, summary="GPU pivot", mentions=312, name="Iris Energy")
    base.update(k)
    return base


# --- preserved behavior ---

def test_email_lists_top_signals():
    html = build_email_html("Jun 1", [dict(ticker="IREN", velocity=9.4, state="new",
                                            pct_bull=78, price=14.2, pct_change=8.1, summary="GPU")])
    assert "IREN" in html and "9.4" in html


def test_email_includes_still_running_block():
    html = build_email_html(
        "Jun 3",
        [_sig()],
        still=[dict(ticker="MRVL", price=308.69, pct_change=6.1, days_running=1)])
    assert "Still Running" in html
    assert "MRVL" in html
    assert "running 1d" in html


def test_email_no_still_block_when_empty():
    html = build_email_html("Jun 3", [_sig()])
    assert "Still Running" not in html


# --- new: helpers ---

def test_pct_and_money_none_render_dash():
    assert _pct(None) == (DIM, "—")
    assert _money(None) == "—"


def test_pct_direction_and_format():
    assert _pct(8.1) == (UP, "▲8.1%")
    assert _pct(-2.0) == (DOWN, "▼2.0%")
    assert _money(14.2) == "$14.20"


# --- new: daily digest cards ---

def test_email_mover_card_shows_fields():
    html = build_email_html("Jun 3", [_sig(ticker="MRVL", name="Marvell",
                                            price=308.69, pct_change=6.1, summary="Huang hype")])
    assert "MRVL" in html
    assert "Marvell" in html
    assert "$308.69" in html
    assert "▲6.1%" in html
    assert "312 mentions" in html        # from _sig default mentions
    assert "Huang hype" in html


def test_email_escapes_summary_xss():
    html = build_email_html("Jun 3", [_sig(summary="<script>alert(1)</script>")])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_email_empty_board_is_graceful():
    html = build_email_html("Jun 3", [])
    assert "No signals" in html
    assert "<table" in html              # still a valid shell, no crash


def test_email_footer_has_dashboard_button():
    html = build_email_html("Jun 3", [_sig()])
    assert DASHBOARD_URL in html
    assert "View live dashboard" in html


# --- new: trump alert ---

def test_trump_email_chips_quote_and_button():
    html = build_trump_alert_email({
        "tickers": ["DJT", "TSLA"],
        "post": "buy <b>now</b>",
        "url": "https://truthsocial.com/x",
        "detected_at": "2026-06-03T19:30:00Z",
    })
    assert "$DJT" in html and "$TSLA" in html
    assert "buy &lt;b&gt;now&lt;/b&gt;" in html      # post escaped
    assert "<b>now</b>" not in html
    assert "View post" in html
    assert "https://truthsocial.com/x" in html
```

- [ ] **Step 2: Run and confirm failures**

Run: `.venv/bin/python -m pytest tests/test_email.py -q`
Expected: FAIL — `ImportError` for `_pct`/`_money`/`DASHBOARD_URL`/`UP`/`DOWN` (they don't exist yet), plus card/chip assertion failures.

- [ ] **Step 3: Commit the tests**

```bash
git add tests/test_email.py
git commit -m "test(email): cover redesigned cards, chips, button, escaping, empty board"
```

---

### Task 4: Rewrite radar/email_report.py

**Files:**
- Rewrite: `radar/email_report.py`

- [ ] **Step 1: Replace the entire file with this content**

```python
from __future__ import annotations
import os, html as _html

DASHBOARD_URL = "https://jtur671.github.io/reddit-signal-radar/"

# brand palette (light variant of the dashboard's terminal theme)
INK = "#16242e"
DIM = "#8b9199"
UP = "#3f9c6d"
DOWN = "#e0654f"
GOLD = "#e0b049"
HAIR = "#e6e9ec"
BG = "#ffffff"
PANEL = "#f6f8fa"

SANS = '-apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'
MONO = '"SF Mono", SFMono-Regular, Consolas, "Liberation Mono", monospace'


def _esc(x) -> str:
    return _html.escape("" if x is None else str(x))


def _pct(value) -> tuple[str, str]:
    """(color, display) for a percent change. None -> em dash."""
    if value is None:
        return (DIM, "—")
    if value < 0:
        return (DOWN, f"▼{abs(value):.1f}%")
    return (UP, f"▲{value:.1f}%")


def _money(value) -> str:
    return f"${value:.2f}" if value is not None else "—"


def _button(href: str, label: str) -> str:
    return (f'<a href="{_esc(href)}" style="display:inline-block;padding:10px 18px;'
            f'background:{INK};color:#ffffff;text-decoration:none;border-radius:6px;'
            f'font-family:{SANS};font-size:13px;font-weight:600">{_esc(label)}</a>')


def _section(label: str) -> str:
    return (f'<div style="font-family:{SANS};font-size:12px;font-weight:700;letter-spacing:1px;'
            f'text-transform:uppercase;color:{DIM};margin:18px 0 4px">{_esc(label)}</div>')


def _shell(preheader: str, subtitle: str, body: str, accent: str = INK) -> str:
    """Outer 600px card: branded header (wordmark + subtitle, tinted by accent), body, footer."""
    return (
        f'<div style="background:{PANEL};padding:24px 0;font-family:{SANS};color:{INK}">'
        f'<span style="display:none!important;opacity:0;color:transparent;height:0;width:0;'
        f'overflow:hidden">{_esc(preheader)}</span>'
        f'<table align="center" width="600" cellpadding="0" cellspacing="0" '
        f'style="max-width:600px;margin:0 auto;background:{BG};border:1px solid {HAIR};'
        f'border-radius:10px;overflow:hidden">'
        f'<tr><td style="padding:18px 24px;border-bottom:2px solid {accent}">'
        f'<table width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td style="font-family:{MONO};font-size:15px;font-weight:700;letter-spacing:1px;'
        f'color:{accent}">📡 SIGNAL RADAR</td>'
        f'<td align="right" style="font-family:{MONO};font-size:12px;color:{DIM}">{_esc(subtitle)}</td>'
        f'</tr></table></td></tr>'
        f'<tr><td style="padding:8px 24px 22px">{body}</td></tr>'
        f'<tr><td style="padding:16px 24px;border-top:1px solid {HAIR};background:{PANEL}">'
        f'<table width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td>{_button(DASHBOARD_URL, "View live dashboard ↗")}</td>'
        f'<td align="right" style="font-family:{SANS};font-size:11px;color:{DIM}">'
        f'Not investment advice.</td>'
        f'</tr></table></td></tr>'
        f'</table></div>'
    )


def _mover_card(s: dict) -> str:
    color, pct = _pct(s.get("pct_change"))
    name = _esc(s.get("name") or "")
    state = _esc((s.get("state") or "").upper())
    chips = f'{_esc(s.get("mentions", ""))} mentions · {_esc(s.get("velocity", ""))}'
    if state:
        chips += f' · {state}'
    summary = _esc(s.get("summary") or "")
    name_html = (f'<div style="font-family:{SANS};font-size:13px;color:{DIM};margin-top:2px">'
                 f'{name}</div>') if name else ""
    summary_html = (f'<div style="font-family:{SANS};font-size:13px;color:{INK};margin-top:8px;'
                    f'line-height:1.45">“{summary}”</div>') if summary else ""
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:10px 0;border:1px solid {HAIR};border-radius:8px;background:{BG}">'
        f'<tr><td style="padding:14px 16px">'
        f'<table width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td style="font-family:{MONO};font-size:22px;font-weight:700;color:{INK}">'
        f'{_esc(s.get("ticker", ""))}</td>'
        f'<td align="right" style="font-family:{MONO};font-size:17px;font-weight:700;color:{color}">'
        f'{_money(s.get("price"))}&nbsp;&nbsp;{pct}</td>'
        f'</tr></table>'
        f'{name_html}'
        f'<div style="font-family:{MONO};font-size:12px;color:{DIM};margin-top:6px">{chips}</div>'
        f'{summary_html}'
        f'</td></tr></table>'
    )


def _rest_table(rows: list[dict]) -> str:
    if not rows:
        return ""
    trs = ""
    for s in rows:
        color, pct = _pct(s.get("pct_change"))
        trs += (
            f'<tr>'
            f'<td style="padding:6px 0;font-family:{MONO};font-size:13px;font-weight:700;'
            f'color:{INK}">{_esc(s.get("ticker", ""))}</td>'
            f'<td style="padding:6px 0;font-family:{MONO};font-size:13px;color:{color}">{pct}</td>'
            f'<td align="right" style="padding:6px 0;font-family:{MONO};font-size:12px;color:{DIM}">'
            f'{_esc(s.get("mentions", ""))} · {_esc(s.get("velocity", ""))}</td>'
            f'</tr>')
    return f'<table width="100%" cellpadding="0" cellspacing="0">{trs}</table>'


def _still_block(still) -> str:
    if not still:
        return ""
    trs = ""
    for s in still:
        color, pct = _pct(s.get("pct_change"))
        trs += (
            f'<tr>'
            f'<td style="padding:6px 0;font-family:{MONO};font-size:13px;font-weight:700;'
            f'color:{INK}">{_esc(s.get("ticker", ""))}</td>'
            f'<td style="padding:6px 0;font-family:{MONO};font-size:13px;color:{color}">'
            f'{_money(s.get("price"))} {pct}</td>'
            f'<td align="right" style="padding:6px 0;font-family:{MONO};font-size:12px;color:{GOLD}">'
            f'running {int(s.get("days_running") or 0)}d</td>'
            f'</tr>')
    return _section("Still Running") + f'<table width="100%" cellpadding="0" cellspacing="0">{trs}</table>'


def build_email_html(date_str: str, signals: list[dict], still: list[dict] | None = None) -> str:
    signals = signals or []
    if not signals:
        body = (f'<div style="font-family:{SANS};font-size:14px;color:{DIM};padding:12px 0">'
                f'No signals on the board today — the tape is quiet.</div>')
        return _shell(f"Signal Radar — {date_str}", date_str, body)
    body = _section("Top Movers") + "".join(_mover_card(s) for s in signals[:3])
    rest = _rest_table(signals[3:])
    if rest:
        body += _section("The Rest") + rest
    body += _still_block(still)
    pre = f"Top: {signals[0].get('ticker', '')} {_pct(signals[0].get('pct_change'))[1]}"
    return _shell(pre, date_str, body)


def build_trump_alert_email(alert: dict) -> str:
    tickers = alert.get("tickers", [])
    chips = "".join(
        f'<span style="display:inline-block;margin:0 6px 6px 0;padding:6px 12px;'
        f'background:#fdf3df;color:{GOLD};border:1px solid {GOLD};border-radius:6px;'
        f'font-family:{MONO};font-size:14px;font-weight:700">${_esc(t)}</span>'
        for t in tickers)
    post = _esc(alert.get("post", ""))
    when = _esc(alert.get("published") or alert.get("detected_at") or "")
    body = (
        f'<div style="font-family:{SANS};font-size:14px;color:{INK};margin:10px 0 8px">'
        f'Trump just named</div>'
        f'<div style="margin-bottom:4px">{chips}</div>'
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:12px 0;border-left:3px solid {DOWN};background:{PANEL};border-radius:4px">'
        f'<tr><td style="padding:12px 14px;font-family:{SANS};font-size:15px;line-height:1.5;'
        f'color:{INK}">“{post}”</td></tr></table>'
        f'<table width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td style="font-family:{MONO};font-size:12px;color:{DIM}">{when}</td>'
        f'<td align="right">{_button(alert.get("url", ""), "View post ↗")}</td>'
        f'</tr></table>'
    )
    pre = "Trump named " + ", ".join("$" + t for t in tickers)
    return _shell(pre, "🚨 PUMP ALERT", body, accent=DOWN)


def _send(subject: str, html: str) -> bool:
    key = os.environ.get("RESEND_API_KEY")
    to = os.environ.get("EMAIL_RECIPIENTS", "")
    if not key or not to:
        return False              # require both an API key and a recipient; no hardcoded address
    import resend
    resend.api_key = key
    sender = os.environ.get("RESEND_FROM", "onboarding@resend.dev")
    resend.Emails.send({"from": sender, "to": to.split(","),
                        "subject": subject, "html": html})
    return True


def send_email(date_str: str, signals: list[dict], still: list[dict] | None = None) -> bool:
    return _send(f"📡 Signal Radar — {date_str}", build_email_html(date_str, signals, still))


def send_trump_alert(alert: dict) -> bool:
    tickers = ", ".join("$" + t for t in alert.get("tickers", []))
    return _send(f"🚨 Trump post mentions {tickers}", build_trump_alert_email(alert))
```

- [ ] **Step 2: Run the email tests**

Run: `.venv/bin/python -m pytest tests/test_email.py -q`
Expected: PASS (all preserved + new tests).

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (no other module imports changed symbols from `email_report`).

- [ ] **Step 4: Commit**

```bash
git add radar/email_report.py
git commit -m "feat(email): branded light HTML — mover cards, ticker chips, dashboard button"
```

---

### Task 5: Render smoke + visual eyeball

**Files:** none (verification only)

- [ ] **Step 1: Render both emails to disk from sample data**

Run:
```bash
.venv/bin/python - <<'PY'
from radar.email_report import build_email_html, build_trump_alert_email
sigs = [dict(ticker="MRVL", name="Marvell Technology", velocity="9.4×", state="hot",
             pct_bull=70, price=308.69, pct_change=6.1, mentions=931,
             summary="Jensen Huang calls it a potential trillion-dollar company"),
        dict(ticker="NVDA", name="NVIDIA", velocity="1.2×", state="sustained",
             pct_bull=64, price=1180.0, pct_change=-1.4, mentions=410, summary="AI demand"),
        dict(ticker="ASML", name="ASML Holding", velocity="3.2×", state="hot",
             pct_bull=60, price=1020.5, pct_change=2.1, mentions=210, summary="EUV orders"),
        dict(ticker="LULU", name="Lululemon", velocity="1.1×", state="sustained",
             pct_bull=55, price=330.0, pct_change=0.4, mentions=120, summary="earnings")]
still = [dict(ticker="SPXC", name="SPX Tech", price=150.2, pct_change=3.0, days_running=1, mentions=90)]
open("/tmp/email_daily.html", "w").write(build_email_html("Jun 3, 2026", sigs, still))
open("/tmp/email_trump.html", "w").write(build_trump_alert_email(
    {"tickers": ["DJT", "TSLA"], "post": "Big things coming for these companies!",
     "url": "https://truthsocial.com/x", "detected_at": "Jun 3 · 7:30pm"}))
print("wrote /tmp/email_daily.html and /tmp/email_trump.html")
PY
```
Expected: prints the two paths, no exception.

- [ ] **Step 2: Sanity-grep the rendered output**

Run:
```bash
grep -c "SIGNAL RADAR" /tmp/email_daily.html /tmp/email_trump.html
grep -o "View live dashboard" /tmp/email_daily.html
grep -o "\$DJT" /tmp/email_trump.html
```
Expected: each file contains `SIGNAL RADAR`; the daily has the dashboard button; the Trump email has the `$DJT` chip.

- [ ] **Step 3: (Optional) open in a browser to eyeball**

Run: `open /tmp/email_daily.html /tmp/email_trump.html`
Expected: both render as branded light cards. (Email clients differ from browsers, but this catches gross layout breaks.)

---

## Self-Review

**Spec coverage:**
- Light/clean branded shell, 600px, inline CSS, no JS/web-fonts → `_shell` (Task 4).
- Daily top-3 mover cards + "the rest" + Still Running → `build_email_html` / `_mover_card` / `_rest_table` / `_still_block` (Task 4) + tests (Task 3).
- Trump chips + quoted post + button, red accent → `build_trump_alert_email` (Task 4) + test (Task 3).
- `_pct`/`_money` em-dash for None → Task 4 + `test_pct_and_money_none_render_dash`.
- XSS escaping preserved → `_esc` everywhere + `test_email_escapes_summary_xss`, trump escape assertion.
- Signatures unchanged (`build_email_html(date_str, signals, still=None)`, `build_trump_alert_email(alert)`) → preserved verbatim; `_send`/`send_email`/`send_trump_alert` unchanged.
- Data adds (`mentions`, `name`) → Task 2.
- monitor.py logging fix shipped → Task 1.
- Dashboard URL footer → `DASHBOARD_URL` in `_shell` + `test_email_footer_has_dashboard_button`.
- Empty board graceful → `build_email_html` early branch + `test_email_empty_board_is_graceful`.

**Placeholder scan:** none — every code/test step is complete and runnable.

**Type consistency:** `_pct` returns `(color, str)` and is consumed as `color, pct = _pct(...)` everywhere; `_shell(preheader, subtitle, body, accent=INK)` matches all three call sites (daily empty, daily, trump); test imports (`_pct, _money, DASHBOARD_URL, DIM, UP, DOWN`) all exist as module-level names in Task 4. `build_email_html`/`build_trump_alert_email` signatures match the tests and the unchanged `run.py`/`monitor.py` callers.
