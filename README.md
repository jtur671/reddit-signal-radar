# Reddit Signal Radar

Reddit Signal Radar scans the busiest trading subreddits through Reddit's public JSON
endpoints, extracts the tickers people are talking about, and scores each one for
**freshness**, **velocity** (mention acceleration vs. its own 90-day baseline), and
**sentiment** — so stale signals always decay off the board instead of lingering. The
top movers are rendered into an infographic dashboard published to GitHub Pages, and the
same board is delivered as a daily email at **6 AM ET**.

## How it works

```
fetch → extract → score → sentiment + enrich → render → publish + email
```

Each run pulls listings/comments from the configured subreddits, extracts and validates
ticker mentions, scores them with a half-life decay model, layers on VADER sentiment plus
theme/price enrichment, renders `out/index.html` + `out/data.json`, then publishes to
GitHub Pages and sends the email. A rolling 90-day `data/history.json` is used as the
velocity baseline and is committed back to the repo on every run.

## Local run

```bash
pip install -r requirements.txt
python3 -m radar.run --dry-run --no-email --subreddits stocks --out out
open out/index.html
```

This runs the full pipeline against r/stocks only, skips the email, and writes the
dashboard to `out/index.html`. The pinned `openai` client is `>=1.59.0,<2` (used to talk
to the DeepSeek-compatible API).

Note: Reddit may rate-limit unauthenticated requests, so seeing an **empty board** when
you run locally is normal — it just means the public JSON returned no usable data on that
attempt.

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

- `config.yaml` — pipeline tunables: half-life (`half_life_hours`), lookback window
  (`lookback_hours`), noise floor (`noise_floor`), top-N (`top_n`), and history retention
  (`history_days`).
- `data/themes.yaml` — theme watchlists (seed tickers + keywords).
- `data/subreddits.txt` — the list of subreddits to scan.
- `data/stoplist.txt` — words/tickers to ignore.

For example, the `infrastructure` theme tracks the `KEEL` ticker (Keel Infrastructure) —
add your own themes the same way by appending a labelled block with `seeds` and
`keywords`.

## Known limitations

- **Sockpuppet brigades.** The noise floor caps any single author's weight and counts
  distinct authors, which defeats a lone high-volume account. A coordinated botnet of
  many throwaway accounts each posting once can still inflate distinct-author counts —
  inherent to author-based weighting without account-age/karma signals.
- **LLM summaries are best-effort.** Untrusted Reddit text is fenced and run through an
  injection sanitizer before reaching the model, and all model output is HTML-escaped
  on the dashboard and in email (so injection cannot become XSS). A determined prompt
  injection could still produce a misleading one-line summary; treat summaries as color,
  not fact.
- **Reddit rate limits.** Unauthenticated public-JSON requests are throttled; an empty
  board on a given run usually means the fetch was rate-limited, not that nothing trended.

## Disclaimer

Not investment advice.
