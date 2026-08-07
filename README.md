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
fetch (ApeWisdom) → score → engagement + price enrich → render → publish + email
```

Each run pulls per-ticker Reddit mention aggregates, scores them against each ticker's
adaptive 90-day EMA baseline (velocity + surprise z-score, noise floor, lifecycle states),
tags themes, adds an upvotes-based **engagement** proxy and yfinance prices, renders
`out/index.html` + `out/data.json`, then publishes to GitHub Pages and sends the email.
A rolling 90-day `data/history.json` is the velocity baseline, committed back every run
to the orphan **`data` branch** (bot state stays out of main's history). Each run also
publishes `out/health.json` (and a `health` block in `data.json`) — a machine-readable
self-assessment (`ok` / `degraded` / `severe`) so downstream consumers can gate on board
quality; severe degradation also triggers an alert email.

> Note: ApeWisdom provides mention counts + upvotes but **no directional (bull/bear)
> sentiment** and no raw comment text — so the dashboard's "engagement" bar is an
> upvotes-per-mention proxy, and DeepSeek summaries are generated from the numbers.

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
   (and optionally `ALPACA_API_KEY` / `ALPACA_SECRET_KEY`). `RESEND_FROM` is also
   optional — it defaults to Resend's `onboarding@resend.dev` test sender; set it to an
   address on a domain you've verified in Resend before adding real recipients.
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
  "see the discussion" link), and the `edgar` / `fed` / `congress` monitor blocks
  (dollar floors, feed URLs, max ages). (Half-life / lookback / `fetch` apply only to
  the legacy raw-Reddit path.)
- `data/themes.yaml` — theme watchlists (seed tickers + keywords) used to tag the board.
- `data/trump_watch.yaml` — company/asset name → ticker map for the Trump monitor.
- `data/congress_watch.yaml` — curated notable members whose purchases always alert.
- `data/*_seen.json` / `data/*_alert.json` — per-monitor dedup cursors and active alert
  state; don't edit by hand. Together with `history.json`/`about.json` these live on the
  orphan **`data` branch** (CI overlays them at checkout and pushes them back there).
  For a local run with real state: `git fetch origin data && git checkout origin/data -- data/`
  — or start cold; `scripts/seed_data_branch.sh` (re)builds the branch from disk.
- `data/stoplist.txt`, `data/subreddits.txt`, `data/universe.txt` — used by the legacy
  raw-Reddit path only.

For example, the `infrastructure` theme tracks the `KEEL` ticker (Keel Infrastructure) —
add your own themes the same way by appending a labelled block with `seeds` and
`keywords`.

## Monitor fleet

A separate workflow (`.github/workflows/fleet-monitor.yml`, every 30 min) runs four
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

## Known limitations

- **Aggregator trust.** Mention counts come from ApeWisdom, so the bot inherits whatever
  scraping/filtering it does. No directional sentiment or raw text is available, so the
  "engagement" bar is an upvotes-per-mention proxy, not a bull/bear reading.
- **Cold start.** Velocity and surprise are measured against the 90-day baseline, which
  starts empty — the first ~1–2 weeks of boards are dominated by "new" until history fills.
- **LLM summaries are best-effort.** Summaries are generated from mention metadata and
  HTML-escaped on output (so they can't become XSS); treat them as color, not fact.
- **Single source of truth.** If ApeWisdom is down, the board is empty for that run; the
  pipeline degrades gracefully (no crash) but there's no fallback feed today — an empty
  board is reported as `severe` in `health.json`.
- **Early Plays are ideas, not orders.** `recommend_buys` surfaces up to 3 LLM-generated
  early-entry candidates as machine-consumable input for downstream trader agents; it
  fails closed (no key or any error → no picks) and the radar itself never places orders.

## Disclaimer

Not investment advice.
