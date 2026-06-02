# Reddit Signal Radar

Reddit Signal Radar tracks which tickers Reddit's trading communities are talking about
and scores each one for **freshness** and **velocity** (mention acceleration vs. its own
90-day baseline) — so stale signals always decay off the board instead of lingering. The
top movers are rendered into an infographic dashboard published to GitHub Pages, and the
same board is delivered as a daily email at **6 AM ET**.

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
A rolling 90-day `data/history.json` is the velocity baseline, committed back every run.

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
   (and optionally `ALPACA_API_KEY` / `ALPACA_SECRET_KEY`).
4. Trigger it once via **Actions → daily-radar → Run workflow** to verify everything
   works before the first scheduled 6 AM run.
5. The schedule is in **UTC**: `0 10 * * *` = 6 AM EDT. Change it to `0 11 * * *` for
   6 AM EST.

## Configuration

- `config.yaml` — pipeline tunables: the `apewisdom` feeds/pages, noise floor
  (`noise_floor`), top-N (`top_n`), EMA smoothing (`ema_alpha`), and history retention
  (`history_days`). (Half-life / lookback / `fetch` apply only to the legacy raw-Reddit path.)
- `data/themes.yaml` — theme watchlists (seed tickers + keywords) used to tag the board.
- `data/stoplist.txt`, `data/subreddits.txt`, `data/universe.txt` — used by the legacy
  raw-Reddit path only.

For example, the `infrastructure` theme tracks the `KEEL` ticker (Keel Infrastructure) —
add your own themes the same way by appending a labelled block with `seeds` and
`keywords`.

## Known limitations

- **Aggregator trust.** Mention counts come from ApeWisdom, so the bot inherits whatever
  scraping/filtering it does. No directional sentiment or raw text is available, so the
  "engagement" bar is an upvotes-per-mention proxy, not a bull/bear reading.
- **Cold start.** Velocity and surprise are measured against the 90-day baseline, which
  starts empty — the first ~1–2 weeks of boards are dominated by "new" until history fills.
- **LLM summaries are best-effort.** Summaries are generated from mention metadata and
  HTML-escaped on output (so they can't become XSS); treat them as color, not fact.
- **Single source of truth.** If ApeWisdom is down, the board is empty for that run; the
  pipeline degrades gracefully (no crash) but there's no fallback feed today.

## Disclaimer

Not investment advice.
