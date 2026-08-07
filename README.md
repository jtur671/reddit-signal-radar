# Reddit Signal Radar

Reddit Signal Radar tracks which tickers Reddit's trading communities are talking about
and scores each one for **freshness** and **velocity** (mention acceleration vs. its own
90-day baseline) — so stale signals always decay off the board instead of lingering. The
top movers are rendered into an infographic dashboard published to GitHub Pages, and the
same board is delivered as a daily email at **6:17 AM ET** (deliberately off the top of
the hour — GitHub delays or drops cron runs scheduled at :00).

**Data source:** Reddit's public JSON endpoints return HTTP 403 to cloud/CI IPs, so the
bot sources per-ticker mention counts from the free, no-auth [ApeWisdom](https://apewisdom.io)
aggregator (`all-stocks` + `all-crypto`). The freshness engine scores those daily counts
against its own 90-day EMA baseline. (The original raw-Reddit fetch/extract/sentiment path
still ships and is tested, for anyone running from a non-blocked residential host.)

## How it works

```
fetch (ApeWisdom + Tradestie sentiment) → score → enrich → render → publish + email
```

Each run pulls per-ticker Reddit mention aggregates, scores them against each ticker's
adaptive 90-day EMA baseline (velocity + surprise z-score, noise floor, lifecycle states),
tags themes, adds an upvotes-based **engagement** proxy and yfinance prices, renders
`out/index.html` + `out/data.json`, then publishes to GitHub Pages and sends the email.
A rolling 90-day `data/history.json` is the velocity baseline, committed back every run
to the orphan **`data` branch** (bot state stays out of main's history). Each run also
publishes `out/health.json` (and a `health` block in `data.json`) — a machine-readable
self-assessment (`ok` / `degraded` / `severe`, plus a `sources` block covering
`apewisdom`/`tradestie`/`finnhub`/`finra`/`cboe`/`cramer` as `ok`/`down`/`fallback`/
`unused`) so downstream consumers can gate on board quality; severe degradation also
triggers an alert email. The free, keyless
[Tradestie](https://tradestie.com/api/v1/apps/reddit) WSB endpoint annotates covered
tickers with directional `ts_bull`/`ts_comments` sentiment and doubles as a fallback
board source when ApeWisdom comes back empty. Early Plays picks are appended to the
append-only `data/plays_log.json`; when picks exist, the board and `data.json` carry an
"Early Plays Track Record" scorecard graded against SPY. Crypto picks are logged but
excluded from grading (`excluded_crypto`), since yfinance can silently price a
same-symbol NYSE equity instead of the crypto asset. A weekly job commits
`data/backtest.json` to the data branch; the next daily run publishes it to Pages as
`out/backtest.json` (see **Weekly backtest** below).

> Note: ApeWisdom provides mention counts + upvotes but **no directional (bull/bear)
> sentiment** and no raw comment text — so the dashboard's "engagement" bar is an
> upvotes-per-mention proxy, and DeepSeek summaries are generated from the numbers.
> Tradestie fills that gap with real `ts_bull`/`ts_comments` for the tickers it covers
> (WSB only); everything outside that coverage still relies on the engagement proxy.

Five more sources widen the signal, each writing into that day's `history.json` entry
and reporting its own `health.json` check, fail-soft on outage: FINRA Reg SHO daily
short-sale volume (`short_ratio`, all covered tickers), CBOE delayed options chains
(`pc_ratio` + a coarse `uoa` unusual-activity flag, top `cboe.top_n` board movers only —
full chains run ~1.6MB/symbol), an EDGAR full-text 8-K tripwire (fleet monitor `edgar8k`,
see **Monitor fleet** below), inverse-Cramer sentiment (`cramer`, vendored to
`data/cramer_snapshot.json` on the data branch each run so the signal survives the
upstream hobby repo disappearing), and Finnhub company headlines feeding the existing
DeepSeek catalyst summaries when `FINNHUB_API_KEY` is set, falling back to the original
Google News RSS search otherwise. `data.json` gains a `signals` array (per board row:
ticker, `composite` 0–100, a `components` breakdown — velocity/direction/engagement/
short_pressure/options/events/cramer_inverse, each 0–100 or `null` when a source doesn't
cover that name — plus the raw `short_ratio`/`pc_ratio`/`uoa`/`cramer` values) and the raw
`weights` config (`config.yaml`'s `composite.weights`, before per-row renormalization —
`radar/composite.py`'s `blend()` drops null components and renormalizes over what's left
per ticker, but that per-row renormalization isn't what's published here). Weights are
heuristic until
`backtest.json`'s `power.sufficient` flips true, then get recalibrated there — a config
change, not a code change; the consuming bot should trust `components` over the single
`composite` number. The composite also shows in the dashboard's per-ticker detail modal.

## Local run

```bash
pip install -r requirements.txt
python3 -m radar.run --dry-run --no-email --out out
open out/index.html
```

This runs the full pipeline (live ApeWisdom data), skips the email, and writes the
dashboard to `out/index.html`. The pinned `openai` client is `>=1.59.0,<2` (used to talk
to the DeepSeek-compatible API). Velocity/surprise only become meaningful after ~1–2 weeks
of `history.json` has accumulated; early boards are "new"-heavy by design.

## Deploy (GitHub Actions)

The daily run is driven by `.github/workflows/daily.yml`.

1. Create a GitHub repo and push this code.
2. Enable **Settings → Pages → Source: GitHub Actions**.
3. Add repo **Secrets**: `DEEPSEEK_API_KEY`, `RESEND_API_KEY`, `EMAIL_RECIPIENTS`
   (and optionally `ALPACA_API_KEY` / `ALPACA_SECRET_KEY`, `FINNHUB_API_KEY`).
   `RESEND_FROM` is also optional — it defaults to Resend's `onboarding@resend.dev` test
   sender; set it to an address on a domain you've verified in Resend before adding real
   recipients. `FINNHUB_API_KEY` is free-tier and optional too — without it,
   `health.json`'s `finnhub` check reports `unused` and headlines fall back to Google News.
4. Trigger it once via **Actions → daily-radar → Run workflow** to verify everything
   works before the first scheduled 6 AM run.
5. The schedule is in **UTC**: `17 10 * * *` = 6:17 AM EDT (off the top of the hour on
   purpose — GitHub delays/drops `:00` crons under load). Change it to `17 11 * * *`
   for 6:17 AM EST in winter.

## Configuration

- `config.yaml` — pipeline tunables: the `apewisdom` feeds/pages, noise floor
  (`noise_floor`), top-N (`top_n`), EMA smoothing (`ema_alpha`), history retention
  (`history_days`), the `still_running` lane (recently-broken-out names kept visible
  after they fall off the top-N), `reddit.discussion_subreddits` (scopes the modal's
  "see the discussion" link), the `tradestie` block (`url`, `max_retries`,
  `sleep_seconds` for the WSB sentiment fetch), and the `edgar` / `fed` / `congress` /
  `edgar_events` monitor blocks (dollar floors, feed URLs/phrases, max ages). Also the
  widen-phase sources: `finra` (`max_lookback_days` for the Reg SHO file walk-back),
  `cboe` (`top_n` chains to pull, `uoa_vol_oi` / `min_volume` for the UOA flag), `cramer`
  (feed `url`, `max_age_days`, `snapshot_path`), and `composite` (`weights` per
  component — heuristic until recalibrated from `backtest.json`). (Half-life / lookback /
  `fetch` apply only to the legacy raw-Reddit path.)
- `data/themes.yaml` — theme watchlists (seed tickers + keywords) used to tag the board.
- `data/trump_watch.yaml` — company/asset name → ticker map for the Trump monitor.
- `data/congress_watch.yaml` — curated notable members whose purchases always alert.
- `data/*_seen.json` / `data/*_alert.json` — per-monitor dedup cursors and active alert
  state; don't edit by hand. Together with `history.json`/`about.json`/`plays_log.json`
  (Early Plays track record), `backtest.json` (weekly signal grading), and
  `cramer_snapshot.json` (vendored inverse-Cramer feed, survives upstream disappearing)
  these live on the orphan **`data` branch** (CI overlays them at checkout and pushes
  them back there).
  For a local run with real state: `git fetch origin data && git checkout origin/data -- data/`
  — or start cold; `scripts/seed_data_branch.sh` (re)builds the branch from disk.
- `data/stoplist.txt`, `data/subreddits.txt`, `data/universe.txt` — used by the legacy
  raw-Reddit path only.

For example, the `infrastructure` theme tracks the `KEEL` ticker (Keel Infrastructure) —
add your own themes the same way by appending a labelled block with `seeds` and
`keywords`.

## Monitor fleet

A separate workflow (`.github/workflows/fleet-monitor.yml`, every 30 min) runs five
tripwire monitors. When any of them fires, it emails immediately and rebuilds the
dashboard with an alert card between the masthead and the board (auto-expires after
48h). Detection is deduped via `data/*_seen.json`; the build/deploy only runs on a new
alert, so the 30-min cadence is cheap.

- **Trump** — polls Donald Trump's Truth Social posts via the free
  [trumpstruth.org](https://www.trumpstruth.org) RSS feed; alerts when a post names a
  ticker or tracked company (cashtags + universe symbols + `data/trump_watch.yaml`).
  (X/Twitter isn't monitored — Trump posts on Truth Social, and the X API is paid-only.)
- **EDGAR insider buys** — watches SEC Form 4 filings market-wide for open-market
  purchases (transaction code P); the single largest fresh buy over the `min_usd`
  floor ($1M by default) alerts per tick.
- **Fed / FOMC** — the Federal Reserve's monetary-policy press feed; every new release
  (statements, projections, minutes) fires one alert tagged with macro tickers
  (SPY/TLT/IWM/GLD). Low volume, ~2–3 a month.
- **Congress** — STOCK Act disclosures from a free no-auth JSON feed; alerts on a
  purchase by a curated notable member (`data/congress_watch.yaml`) or any purchase
  above `min_usd` ($250k by default). Note disclosures can lag the trade by up to 45
  days.
- **EDGAR 8-K events** — full-text-searches EDGAR (`efts.sec.gov`, date-bounded to the
  last day) for high-salience 8-K phrases (`edgar_events.phrases`, e.g. "material
  definitive agreement", "bankruptcy"); alerts only when the filer maps to a ticker with
  recent `history.json` activity (multi-ticker EDGAR display names are matched too).

## Weekly backtest

`.github/workflows/backtest.yml` (Sundays 11:41 UTC + manual dispatch) runs
`python -m radar.backtest`, self-grading whether the velocity/surprise signal actually
predicts anything: quintile forward excess returns (1/5/10d vs SPY and IWM), daily rank
IC with Newey-West t-stats, an event study around hot-transitions, a forward-volatility
quintile test, and the Early Plays scorecard, plus `price_coverage`, a `power` check
(needs 150 days of history; not there yet), and dated `regime_notes` for signal-changing
commits. Prices are taken from the first trading day *strictly after* the signal day —
no same-day look-ahead. Results commit to `data/backtest.json` on the data branch; the
daily run copies it to `out/backtest.json`. On price-fetch failure the job fails loudly
rather than overwrite the last good artifact.

## Known limitations

- **Aggregator trust.** Mention counts come from ApeWisdom, so the bot inherits whatever
  scraping/filtering it does. No directional sentiment or raw text is available on that
  path, so the "engagement" bar stays an upvotes-per-mention proxy, not a bull/bear
  reading, for tickers Tradestie doesn't cover.
- **Cold start.** Velocity and surprise are measured against the 90-day baseline, which
  starts empty — the first ~1–2 weeks of boards are dominated by "new" until history fills.
- **LLM summaries are best-effort.** Summaries are generated from mention metadata and
  HTML-escaped on output (so they can't become XSS); treat them as color, not fact.
- **ApeWisdom is still the primary source.** If it's down, Tradestie's WSB top-50 steps
  in as a partial-board fallback (`health.json`'s `sources.apewisdom` flips to `down`,
  `sources.tradestie` to `fallback`); if both are empty the board is empty and reported
  `severe`.
- **Early Plays are ideas, not orders.** `recommend_buys` surfaces up to 3 LLM-generated
  early-entry candidates as machine-consumable input for downstream trader agents; it
  fails closed (no key or any error → no picks) and the radar itself never places orders.

## Disclaimer

Not investment advice.
