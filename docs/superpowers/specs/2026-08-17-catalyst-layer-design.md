---
project: Reddit Signal Radar
phase: E1 — Catalyst layer
spec: design
date: 2026-08-17
status: approved (owner, 2026-08-17)
research: [[2026-08-17-community-mining]]
---

# E1 — Catalyst layer

Teach the radar to see the SEC filings that actually move small caps — dilution,
activist stakes, delisting — and fix the composite component they would otherwise
corrupt.

## 1. Why

The fleet already full-text-searches EDGAR every 30 minutes. `edgar_events.py:17`
hardcodes `&forms=8-K` into the query template; the endpoint accepts any form code.
Four classes are worth adding (all volumes **measured 2026-08-10→14, 5 trading days,
market-wide**):

| Class | Form | `q` phrase | Meaning | Filings/5d |
|---|---|---|---|---|
| `dilution` | `424B5` | `at the market offering` | Shares being sold **now** | 45 |
| `shelf` | `S-3,S-3ASR` | `offering` | Permission to sell later | 35 |
| `activist` | `SCHEDULE 13D` | `common stock` | Investor >5%, intends change | 90 |
| `delisting` | `25-NSE` | `delisting` | Removal from the exchange | 2 |

(Counts are **unique filings**, de-duplicated per §2.2.1 — not the raw hit totals, which
run 1.0–2.9× higher. `forms=` accepts comma-separated codes: `S-3,S-3ASR` returns
exactly `S-3` + `S-3ASR`, verified.)

The motivating case: **MVIS** filed a 424B5 on 2026-08-13 in the same week
r/pennystocks' top-of-month called it a reverse-split squeeze candidate. Hype and
dilution on one name, and the radar cannot see half of it.

### 1.1 Blocking defect — `events` is broken twice over

`composite.py:43`:

```python
"events": 100.0 if s.ticker in alert_tickers else 0.0,
```

`run.py:154` builds `alert_tickers` as a **flat set across every monitor**, discarding
`monitor_key`. Two independent failures:

**(a) Unsigned.** Every other component is oriented *higher = more interesting to a
buyer* (`cramer_inverse` maps `strong_buy`→0, `sell_avoid`→100; `direction` is bullish
share). So `events` currently asserts "something happened, and that is bullish."
Adding `dilution` and `delisting` under that rule would score a company **+100 for
diluting its shareholders** — the radar would rank it higher for doing it.

**(b) Dead weight.** Measured on the live board, 2026-08-17:

```
events component distribution across 15 rows: {0.0: 15}
```

Zero variance. Tripwires fire on ~3 tickers/day market-wide and rarely overlap the
15-row board, so `0.0` almost always means *"nothing happened"* — but it is scored as a
real zero, not as missing data. The component consumes **10% of the composite weight**
and discriminates nothing: a uniform 10-point drag on every ticker.

Both are fixed by the same change, and `monitor_key` is already persisted into each
alert file by `base.py:53` — the information is thrown away, not missing.

## 2. Design

### 2.1 Signed `events` (do this first — it is what makes the rest safe)

`Monitor` gains one attribute: `direction: "bullish" | "bearish" | "neutral"`.

| Monitor | direction |
|---|---|
| `edgar` (insider buy), `activist` | `bullish` |
| `dilution`, `delisting` | `bearish` |
| `trump`, `fed`, `congress`, `edgar8k`, `shelf` | `neutral` |

`congress` is `neutral` rather than `bullish`: it alerts on purchases, but disclosure
lags the trade by up to 45 days, so treating it as fresh bullish news overstates it.
`shelf` is `neutral` rather than `bearish`: permission to sell is not selling, and the
`dilution` class covers the sale itself.

Mapping, in `composite.py`:

```python
EVENT_DIRECTION = {"bearish": 0.0, "neutral": 50.0, "bullish": 100.0}
...
"events": EVENT_DIRECTION.get(alert_direction.get(s.ticker)),   # None when quiet
```

**`None` when no fresh alert covers the ticker.** `blend()` already drops `None`
components and renormalizes the remaining weights — so a quiet ticker simply doesn't
have the component, instead of being punished with a real zero. No new machinery, no
new weight, no recalibration debt.

**Conflict rule: bearish wins, then bullish, then neutral.** If one ticker has several
fresh alerts, the most negative takes the component. Rationale: a filed dilution is a
hard fact about share supply that an activist stake does not undo, and a radar should
fail toward warning. Every individual alert card still renders, so nothing is hidden —
only the single blended number is opinionated. (Measured relevance: `REPL` drew a
424B5, an S-3ASR *and* a SCHEDULE 13D inside one week.)

`run.py:154` changes from a `set[str]` to a `dict[str, str]` of ticker → direction.

### 2.2 Form-parameterized EDGAR monitor

Generalize `EdgarEventsMonitor` rather than adding a class: today's 8-K monitor becomes
one config row like the rest.

- `EFTS` template takes `forms` and `q` as parameters, not constants.
- Constructor takes `key`, `label`, `card_style`, `direction`, `forms`, `phrases`,
  `watch_days`, `max_age_h`, `user_agent`.
- `active_tickers(days=watch_days)` — **90 for the four new classes** (654 tickers),
  **7 unchanged for `edgar8k`** (148 tickers). Widening the existing 8-K monitor would
  silently change a live monitor's alert volume; that is a separate decision.

Two EDGAR mechanics that are easy to get wrong, both verified 2026-08-17:

- The form code is **`SCHEDULE 13D`**. `SC 13D` returns zero hits.
- **`display_names[0]` is the subject company** (carries the ticker); `[1]` is the
  activist filer (no ticker). `parse_hits` taking `[0]` is correct as written, and
  `_DISPLAY_TICKER` requires `(TICKER)  (CIK`, which only the subject has — so the
  monitor is robust even if EDGAR reorders. `display_names[1]` is free summary text
  ("…filed by Levinson Sam") and should be used in the alert body for `activist`.

#### 2.2.1 Dedup on the accession number, not the filename

EFTS indexes **every file in a submission separately** — the primary document *and* each
exhibit. `parse_hits` currently uses `h["_id"]`, which is `"<accession>:<filename>"`, as
the dedup key. That is one key per *file*, so a single filing can alert repeatedly across
ticks. Measured 2026-08-10→14:

| Query | Hits on page | Unique filings | Worst single filing |
|---|---|---|---|
| `8-K` + `material definitive agreement` | 100 | **100** | 1 file |
| `424B5` + `at the market offering` | 46 | 45 | 2 files |
| `SCHEDULE 13D` + `common stock` | 100 | 90 | 2 files |
| **`S-3,S-3ASR` + `offering`** | 100 | **35** | **6 files** |

This is why the live 8-K monitor never exposed the bug — `"material definitive
agreement"` appears only in the primary document, so its ratio is exactly 1.0. But
`"offering"` appears in the S-3 body *and* in its underwriting agreement, legal opinion
and filing-fee exhibits, giving **2.9× duplication**.

**Fix:** `parse_hits` sets `id` to the accession number (`_id.partition(":")[0]`), and
dedups within a tick on it. The document URL still needs the filename, so keep parsing
both — only the *identity* changes.

**One-time cursor migration.** Existing `data/edgar8k_seen.json` entries are
`"<accession>:<filename>"` and will not match the new accession-only keys, so the first
tick after deploy could re-alert on filings already seen. Strip the `:<filename>` suffix
from existing entries when loading a cursor that predates this change. `max_age_h: 24`
bounds the blast radius to a day either way, but the migration makes it zero.

**The `q` phrase is the debt/equity discriminator.** Measured on 424B5 over 5 trading
days, intersected with the 90-day history:

| `q` | Tickers matched | Megacap debt noise |
|---|---|---|
| `offering` | AMD, IBM, ICE, INTC, OTLK, REPL, RKLB, SMR, UPS, … | **5** |
| **`at the market offering`** | **EU, OTLK, REPL, RKLB, SMR** | **0** |

With `q="offering"`, the 424B5 hits are dominated by investment-grade *bond* shelf
takedowns (AMD, IBM, UPS) — the opposite of a small-cap dilution signal. No market-cap
or price filter is needed; the phrase does the work. **Each class carries its own `q`.**

### 2.3 Config

`config.yaml` gains one list. Adding a class is a config row, not code:

```yaml
edgar_forms:
  - key: dilution
    label: "💧 Dilution"
    direction: bearish
    forms: "424B5"
    phrases: ["at the market offering"]
    watch_days: 90
    max_age_h: 24
  - { key: shelf,     label: "📄 Shelf Filed",   direction: neutral,
      forms: "S-3,S-3ASR",    phrases: ["offering"],      watch_days: 90, max_age_h: 24 }
  - { key: activist,  label: "🎯 Activist 13D",  direction: bullish,
      forms: "SCHEDULE 13D",  phrases: ["common stock"],  watch_days: 90, max_age_h: 48 }
  - { key: delisting, label: "🚫 Delisting",     direction: bearish,
      forms: "25-NSE",        phrases: ["delisting"],     watch_days: 90, max_age_h: 48 }
```

Excluded deliberately: **`SCHEDULE 13G`** (~1,300/5d — passive stakes, volume not
signal) and **`NT 10-Q`** (~96/6d — late filings, too noisy for the salience it carries).

### 2.4 Alerting and rendering

Each class is its own monitor instance, so each gets its own `_seen` cursor and its own
`_alert.json`, and `run_fleet` renders one card per class. Each emails on fire, exactly
like the existing five — owner-approved; dilution and delisting are time-sensitive and
a next-morning board entry is worth much less.

`run_fleet` alerts on `signals[0]` only, so **ordering is load-bearing**: monitors must
return most-salient-first. For form monitors, salience is `file_date` descending, ties
broken by EFTS relevance order (the order hits arrive). Every non-alerting hit still
advances the cursor via `evaluated`, so nothing re-alerts on the next tick.

**No render change.** `write_alert` files are self-describing and
`dashboard.html.j2:268` emits `class="alert alert-{{ a.style }}"`. Reuse the existing
palette by direction: bearish → base `.alert` (already red, no modifier needed),
bullish → `insider` (green), neutral → `fed` (blue). Distinct per-class styling is a
follow-up, not part of this phase.

### 2.5 Expected volume

Measured over 2026-08-10→14: **~3.2 unique alerting tickers/day** at the 90-day gate
(vs ~1.2 at 7 days). That is with the noisy `q="offering"` variant; the tuned phrases
cut it further. `run_fleet` writes only the single most-salient signal per monitor per
tick and dedups via the `_seen` cursor, so each filing alerts once.

## 3. Data contract

`data.json` `signals[].components.events` changes meaning:

| | before | after |
|---|---|---|
| bad-news catalyst | `100.0` | `0.0` |
| neutral catalyst | `100.0` | `50.0` |
| good-news catalyst | `100.0` | `100.0` |
| no fresh alert | `0.0` | `null` |

`weights` is unchanged — `events` keeps its 0.10, and per-row renormalization already
handles the new `null`s. **This is a backtest regime boundary**: every composite shifts.
Add a dated `regime_notes` entry in the same commit.

## 4. Testing

TDD, per repo convention. New/changed coverage:

- `EVENT_DIRECTION` mapping, including `None` for an uncovered ticker.
- Conflict rule: bearish beats bullish beats neutral for one ticker.
- `blend()` drops a `None` `events` and renormalizes to 1.0 (guard the existing
  behaviour against regression, since this is the first component that is routinely
  `None`).
- Form parameterization: the EFTS URL carries the configured `forms` and `q`.
- `active_tickers(days=90)` widens the watch set vs `days=7`.
- `parse_hits` extracts the subject-company ticker from a two-element
  `display_names` (13D shape) and a one-element one (424B5 shape).
- **Dedup by accession:** six hits sharing one accession with different filenames
  produce exactly one signal (the S-3 case, §2.2.1).
- **Cursor migration:** a legacy `seen` list of `"<accession>:<filename>"` entries
  suppresses a new-format `"<accession>"` signal for the same filing.
- `run_fleet` still writes one alert per monitor per tick with five EDGAR monitors
  registered (guards against the registry change fanning out alerts).
- Registry builds five EDGAR monitors from config with distinct `key`s.
- Existing `edgar8k` behaviour is unchanged: still `forms=8-K`, still `watch_days=7`.

Full suite must stay green (327 passing as of 2026-08-17).

## 5. Risks

- **Alert fatigue.** ~3.2/day is an estimate from one 5-day window. Measure real volume
  a week after launch and record it in [[HANDOFF]] §4; if it lands ≥2× the estimate,
  tighten `q` or `watch_days` rather than dropping a class.
- **EFTS paging — the live 8-K monitor is closer to this edge than expected.** The
  endpoint caps at **100 hits/page** and `parse_hits` reads page 1 only. Measured: the
  monitor's own `"material definitive agreement"` query returns **218 hits over 5 trading
  days** ≈ 44/day, and the monitor queries a ~2-day window (`startdt = today − 1`), so a
  single phrase already sits near ~87 — under the cap, but not comfortably, and that is
  one of three configured phrases. Log a warning whenever a query returns exactly 100;
  paging is out of scope for this phase but the warning is not.
- **Ticker mapping.** Only filings whose `display_names` carry a ticker can alert;
  private filers and funds are skipped. This is existing `parse_hits` behaviour, not new.
- **Conflict rule is a judgement call**, not a measured one. Revisit once the backtest
  has power (≈2026-11-01).

## 6. Out of scope

Distinct per-class card styling · reverse-split detection · `SCHEDULE 13G` · `NT 10-Q` ·
FilingFirehose's buried-8-K classifier · widening `edgar8k`'s own watch gate ·
cross-class co-occurrence scoring (recorded as an open question in the research notes).
