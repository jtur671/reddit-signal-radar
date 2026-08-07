# Measure & Widen — Design Spec

> **Date:** 2026-08-07 · **Status:** approved direction, spec under owner review
> **Research:** `docs/research/2026-08-07-next-level.md`
> **Decision (owner):** directions 1+2 — measurement layer first, then signal breadth.
> No LLM agent/debate layer: this project stays **isolated to data**; a separate
> downstream trading bot is the primary consumer of everything published here.

## Context & goals

The radar publishes a daily scored board and Early Plays picks, but nothing measures
whether either predicts anything — picks are overwritten every run, and the literature
warns the naive read may be backwards (extreme attention spikes lean *reversal* at 5–20
days; the robust effect is attention → volatility). Meanwhile the products that won this
niche (Quiver, Unusual Whales) won on composite per-ticker scores and published track
records.

**Goals**
1. A self-grading loop: forward-return/volatility backtest of the velocity signal and a
   live Early Plays scorecard, published machine-readable.
2. Start every data clock now: directional sentiment, short pressure, options activity,
   Cramer picks — each accrues history from merge day even before it's used.
3. A composite per-ticker score with transparent components the trading bot can consume
   (or ignore in favor of raw components).

**Non-goals**
- No order placement, no LLM analyst/debate layer, no paid data (Unusual Whales API has
  no free tier — skipped), no latency-tiering/product/monetization work.
- The dashboard gets minimal additions (scorecard block, component chips); no per-ticker
  drill-down *pages* this arc — the JSON is the drill-down.

## Phase 1 — Measure + start the clocks

### 1a. Early Plays log — `radar/plays_log.py`
Every daily run appends that day's `recommend_buys` output to `data/plays_log.json`
(orphan `data` branch, alongside `history.json`):

```json
{"picks": [{"date": "2026-08-08", "ticker": "XYZ", "thesis": "…", "risk": "…",
            "conviction": "high", "mentions": 42, "vel": "3.2x", "state": "hot"}]}
```

Append-only; dedupe key `(date, ticker)`; no prices stored (the backtest joins prices —
one source of truth). Failure to log warns via `degrade.warn` and never blocks the board.

### 1b. Backtest harness — `radar/backtest.py` + `.github/workflows/backtest.yml`
Weekly (Sunday) + `workflow_dispatch`. Inputs: `history.json`, `plays_log.json`, EOD
prices via yfinance batch download — restricted to tickers that ever appeared on a board
or in the top velocity quintile, plus SPY/IWM benchmarks.

Pre-committed test set (no fishing beyond these):
1. **Quintile forward returns** — daily velocity-score quintiles → mean excess return
   (vs SPY and IWM) over t+1→t+2, t+1→t+6, t+1→t+11. Signal from day *t* is priced at
   **t+1 open at the earliest** — never same-day close (enforced by test, see Testing).
2. **Rank IC** — daily Spearman(score, forward excess return), mean IC + Newey-West
   t-stat; effective N = number of days.
3. **Event study** — cumulative excess return −5…+20d around lifecycle transitions.
4. **Volatility test** — quintiles vs forward realized volatility (the test the
   literature says should pass).
5. **Early Plays scorecard** — per-pick forward excess returns from first tradeable open
   after pick date; aggregate win rate + mean excess vs SPY, overall and by conviction.

Output: `out/backtest.json` — one document with `as_of`, per-test result blocks, a
`power` block (`{"days": N, "sufficient": days >= 150, "target_days": 150}`), and
`regime_notes` (dated entries for methodology changes — first entry: the PR #4 merge
date, after which history `state` becomes board-relative for board names). Every number
ships with its sample size; the consuming bot decides what to trust.

The daily run recomputes only the (cheap) Early Plays scorecard and embeds it as a
`scorecard` block in `data.json`; the dashboard renders it as a small
"picks since 2026-08: X% vs SPY (n=…)" card — honest-hypothetical disclaimer included.

### 1c. Tradestie ingestion — `radar/tradestie.py`
Daily fetch of `api.tradestie.com/v1/apps/reddit` (free, keyless, verified live).
For covered tickers, writes `ts_bull` (0–100 bullish share) and `ts_comments` into that
day's `history.json` entry — filling the currently dead `pct_bull` dimension — and
serves as a **partial-board fallback** when ApeWisdom is down (top-50 WSB only; the
`health.json` block reports which source fed the board). Fail-soft per `degrade.warn`.

## Phase 2 — Widen the signal

Each source is an independent module with the same contract: fetch → per-ticker fields
into enrichment + `history.json` → fail-soft with a `DEGRADED:` log line → a named check
in `health.json`. Ordered by (verified availability × lift):

| # | Source / module | Adds per ticker-day | Notes |
|---|---|---|---|
| 2a | FINRA daily short-sale volume — `radar/shorts.py` | `short_ratio` (ShortVolume/TotalVolume) | CDN text file, keyless, verified |
| 2b | CBOE delayed options — `radar/options.py` | `pc_ratio`, `uoa` spike flag | Top ~10 board names only (~1.6MB/symbol) |
| 2c | EDGAR 8-K full-text tripwire — `radar/monitors/edgar_events.py` | fleet alert on material events, plus a per-ticker `events` count (8-K hits in last 24h) written into enrichment for the composite | Monitor #5 on the existing `run_fleet` framework; SEC UA rules already handled |
| 2d | Finnhub headlines — extend `radar/news.py` | headline count + titles feeding existing summaries | **Needs owner: free `FINNHUB_API_KEY` secret** |
| 2e | Inverse Cramer — `radar/cramer.py` | `cramer` sentiment enum + `cramer_date` | Fetch pinned `stock_sentiments.json` from the `analyzing-stock-calls` GitHub repo (keyless raw URL); vendor a dated snapshot to `data/` each run so the signal survives upstream disappearance; treat as advisory color |
| 2f | Composite score — `radar/composite.py` | `composite` 0–100 + `components` map | Last — needs 2a–2e fields |

**Composite contract** (per board row in `data.json`):

```json
"components": {"velocity": 78, "direction": 55, "engagement": 40,
               "short_pressure": 62, "options": null, "events": 0, "cramer_inverse": null},
"composite": 61
```

Weights live in `config.yaml` under `composite:` (documented, initial values heuristic);
`null` components (source down / not covered) are excluded with weight renormalization,
and `data.json` records the weights used. When `backtest.json.power.sufficient` turns
true, weights get recalibrated from measured ICs — a config change, not a code change.

**Stretch (not committed):** Stocktwits trending/streams — Cloudflare-fronted; include
only if a one-off smoke test from a real Actions runner passes. Curated Substack RSS —
backlog until specific pick-heavy letters are chosen.

## Sequencing & dependencies

0. **Merge PR #4 first** (pending owner decision) — still valid (board remains ~all-hot,
   merges clean, 209 tests green); its merge date is `regime_notes[0]`. Close PR #3 as
   superseded.
1. Phase 1 in order 1a → 1c → 1b (log + clocks start accruing immediately; harness
   follows). Scorecard block lands with 1b.
2. Phase 2 in table order; composite last. Each source merges independently — no
   big-bang.

Owner-provided secrets: `FINNHUB_API_KEY` only. Everything else is keyless.

## Error handling & health

- All fetchers: timeout + fail-soft, `degrade.warn` breadcrumb, never crash the run.
- `health.json` gains one named check per source (`tradestie`, `finra`, `cboe`,
  `finnhub`, `cramer`); board-feeding source degradation escalates per existing
  ok/degraded/severe rules. Backtest failures mark `backtest: degraded` in the *next*
  daily health block but can never block or degrade the board itself.
- `plays_log.json` and vendored Cramer snapshots ride the existing `data`-branch
  commit-back; a push failure there is already a warned, non-fatal path.

## Testing

- Unit tests with fixture payloads per source module (same pattern as `test_apewisdom`).
- **Look-ahead invariant test**: backtest helper that maps signal-date → first tradeable
  price date must always return ≥ t+1; a fixture where same-day close would flatter the
  signal must show the harness ignoring it.
- Scorecard math tested against a hand-computed fixture (known picks + known prices).
- Composite: renormalization under null components; weights-sum property test.
- Existing CI gates (`test.yml` + pre-publish pytest) unchanged; suite stays green at
  every merge point.
