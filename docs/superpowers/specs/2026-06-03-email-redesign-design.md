# Email Redesign — Design

**Date:** 2026-06-03
**Status:** Approved (pending spec review)

## Problem

Both radar emails in `radar/email_report.py` are bare HTML `<table>`s with no branding:
- `build_email_html(date_str, signals, still=None)` — daily digest: one flat table of
  ticker / velocity / %bull / price / summary, plus a minimal "Still Running" table.
- `build_trump_alert_email(alert)` — Trump pump alert: a heading, the post text, a link.

The user wants polished, branded HTML with prominent "big callout" hero elements.

## Decisions (from brainstorm)

- **Scope:** both emails.
- **Visual direction:** light & clean — white background, dark ink text (`#16242e`), brand
  colors used *only* on numbers/chips. (Most readable across clients; least likely to be
  force-inverted.)
- **Daily hero:** the **top 3 movers as big callout cards**, then the rest as a compact list.
- **Brand:** mirrors the dashboard's palette — up `#3f9c6d`, down `#e0654f`, gold `#e0b049`,
  ink `#16242e`, hairline `#e6e9ec` on white. A monospace stack on numeric values keeps a
  terminal nod; everything else uses a system sans stack.

## Email-client constraints (hard requirements)

- **Inline CSS only**, table-based layout, fixed max-width **600px**, centered.
- **No JavaScript, no external CSS, no web fonts.** Font stacks:
  - sans: `-apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`
  - mono (numbers): `"SF Mono", SFMono-Regular, Consolas, "Liberation Mono", monospace`
- All user-influenced text (`ticker`, `summary`, `post`, `name`, `url`) passes through
  `html.escape` (XSS-safe — preserves the current behavior).
- Links rendered as bulletproof buttons (padded `<a>` with inline bg/color).
- A hidden **preheader** span (inbox preview line), visually clipped.

## Architecture

Refactor `email_report.py` around small, single-purpose helpers so both emails share layout
and the file stays readable:

- **Palette constants** — module-level dict/consts for the hex colors + the two font stacks.
- `_shell(preheader: str, title: str, subtitle: str, body: str, accent: str = "#16242e") -> str`
  — outer 600px table, light header (wordmark `SIGNAL RADAR` + subtitle/date, with the header
  rule/title tinted by `accent`), footer (live-dashboard button + "Not investment advice"),
  hidden preheader. Used by BOTH emails; the Trump alert passes `accent="#e0654f"` (red) so its
  header reads as an alert while the daily uses the default ink.
- `_pct(value: float | None) -> tuple[str, str]` — returns `(color_hex, display)` for a
  percent change, e.g. `(#3f9c6d, "▲6.1%")`, `(#e0654f, "▼2.1%")`, `(#8b9199, "—")` for None.
- `_money(value: float | None) -> str` — `"$308.69"` or `"—"`.
- `_mover_card(s: dict) -> str` — big daily callout: ticker (large), company name,
  price + %change (large, colored), a chip row (`{mentions} mentions · {velocity} · {STATE}`),
  and the escaped `summary` ("why it's trending"). Hidden gracefully if fields are missing.
- `_rest_row(s: dict) -> str` — compact row for board names beyond the top 3:
  ticker · %change · `{mentions} · {velocity}`.
- `_still_card(s: dict) -> str` — compact Still Running card: ticker, name, price/%change,
  `running {days_running}d`.
- `_button(href: str, label: str) -> str` — bulletproof button.

`DASHBOARD_URL = "https://jtur671.github.io/reddit-signal-radar/"` (verified via the Pages API).

### `build_email_html(date_str, signals, still=None)` — unchanged signature

```
SIGNAL RADAR · daily                 {date_str}
─────────────────────────────────────────────────
TOP MOVERS
  _mover_card(signals[0])
  _mover_card(signals[1])
  _mover_card(signals[2])
THE REST                       (signals[3:], compact _rest_row each)
STILL RUNNING                  (still, _still_card each — omitted if empty)
─────────────────────────────────────────────────
[ View live dashboard ↗ ]      Not investment advice
```

- Top-3 = `signals[:3]`; "the rest" = `signals[3:]`. With ≤3 signals, "THE REST" is omitted.
- With 0 signals, the body shows a quiet "No signals on the board today." line (no cards).
- The Still Running section keeps `_still_block`'s "omitted when empty" behavior, restyled.

### `build_trump_alert_email(alert)` — unchanged signature

```
🚨 TRUMP PUMP ALERT
─────────────────────────────────────────────────
Trump just named   [ $DJT ]  [ $TSLA ]     (gold ticker chips)
  ┌ quoted post text, larger line-height ┐
Jun 3 · 7:30pm        [ View post ↗ ]
─────────────────────────────────────────────────
Reddit Signal Radar · Not investment advice
```

- Ticker chips from `alert["tickers"]`; quote block from escaped `alert["post"]`;
  timestamp from `alert.get("published") or alert.get("detected_at")`; button → `alert["url"]`.
- Uses `_shell` with a red/gold alert header instead of the neutral daily header.

## Data additions (`radar/run.py`)

The card layout needs a couple more fields than the current row builders emit:

- `_email_row(s)` → add `mentions=s.mentions` and `name=s.name`.
- `_still_email_row(s)` → add `name=s.name` (and `mentions=s.mentions` for parity).

No call-site signature changes; `build_*` inputs stay dict-shaped.

## Folded-in fix

`radar/monitor.py` currently swallows Trump-alert email errors (`except Exception: pass`).
The matching logging fix (already staged) ships with this change so a failed alert email is
visible in CI logs (`EMAIL: trump alert send failed — …`), mirroring the daily path.

## Testing (`tests/test_email.py`)

Preserve existing assertions:
- `test_email_lists_top_signals` — `IREN` and `9.4` still present.
- `test_email_includes_still_running_block` — `Still Running`, `MRVL`, `running 1d`.
- `test_email_no_still_block_when_empty` — no `Still Running` when `still` is empty/None.

Add:
- Mover card renders ticker, escaped company name, price, %change, and summary for `signals[0]`.
- `<script>` in `summary` is escaped (not injected raw).
- Trump email renders a `$DJT`-style chip per ticker, escapes the post, and contains the
  `View post` button with the `url`.
- `DASHBOARD_URL` appears in the daily email footer button.
- Empty `signals` → "No signals" copy, no card markup, no crash.
- `_pct(None)` / `_money(None)` render `—`.

## Out of scope

- No change to what data is collected or how the dashboard renders.
- No new email types or scheduling changes.
- No dark-mode-specific email variant (light design is intentionally client-agnostic).
