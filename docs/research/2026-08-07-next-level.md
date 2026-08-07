---
project: Reddit Signal Radar
topic: "Next level" research — evidence, data sources, product landscape
date: 2026-08-07
status: research notes (pre-decision)
---

# Taking the Radar to the Next Level — Research Notes

Three parallel research passes (academic evidence, data-source landscape, comparable
products) plus a repo/data audit. Raw findings preserved here; the decision and design
live in the spec that follows from them.

## Repo/data audit (measured 2026-08-07)

- `data` branch history.json: **642 tickers, 66 daily snapshots (2026-06-02 → 2026-08-07),
  ~7,800 ticker-day observations**. Fields per ticker-day: raw, weighted, score, state,
  pct_bull (mostly 0 — ApeWisdom has no direction), authors (0 on the ApeWisdom path).
- **Early Plays picks are not archived.** `recommend_buys` output ships in each day's
  `data.json` and is overwritten next run — the radar has no track record of its calls,
  and no forward-return record for the board either.
- PRs #3 (roadmap docs) and #4 (Phase B signal tuning) open untouched since 2026-06-27;
  #3 looks superseded by the ROADMAP.md now on main.

## Evidence: does attention velocity predict returns?

- **Barber, Huang, Odean & Schwarz (J. Finance 2022)** — intense retail attention/herding
  episodes → **−4.7% average 20-day abnormal returns** (reversal), worse for extreme
  episodes, concentrated in small/meme caps. Most directly relevant to a pure
  mention-spike signal.
- **Bradley et al. (RFS 2024, SSRN 3806065)** — WSB due-diligence posts had real momentum
  (+1.1% 2-day, ~+5%/quarter) **only pre-GameStop**; post-2021 the predictability is gone.
  Replicated by 2023 studies (e.g. PMC10111308).
- **Hu, Jones, Zhang & Zhang (2021)** — opposite sign (Reddit traffic → higher near-term
  returns) in the meme-era sample; likely self-fulfilling price pressure.
- **Robust channel: attention → volatility/turnover**, not direction (IRFA 2024, arXiv
  2301.00248, FRL 2026). Comment *volume* beats sentiment scores in several WSB studies —
  convenient, since ApeWisdom is volume-only.
- **Net read**: velocity is most defensible as a **volatility/watchlist signal, likely
  contrarian at 5–20d for extreme spikes** — not a naive buy signal. This is testable on
  our own data.

### Minimal honest backtest protocol

1. Signal from day *t* is tradeable at **t+1 open** at the earliest (never same-day close).
2. Daily quintiles of velocity score → mean t+1→t+2 / t+1→t+6 / t+1→t+11 excess returns
   (vs SPY or IWM); report Q5−Q1 spread + monotonicity.
3. Daily rank IC (Spearman) with Newey-West t-stat; **effective N ≈ #days, not
   ticker-days** — 66 days is suggestive at best; ~100–150 daily cross-sections for a
   t≈2 read on IC≈0.03. Keep collecting toward 150–250 days.
4. Event study around lifecycle transitions (−5..+20d cumulative excess return); want 50+
   events.
5. **Volatility test** (quintiles vs forward realized vol) — most likely to pass.
6. Robustness: drop permanent-megacap names, split by cap, block-bootstrap by day
   (cross-sectional t-stats are overstated on meme days). Pre-commit to ~3 tests.

## Data sources (curl-verified 2026-08-07 unless noted)

| Source | Provides | Access | Verdict |
|---|---|---|---|
| **Tradestie Reddit API** | Top-50 WSB tickers with **directional Bullish/Bearish sentiment** + comment counts; historical by date; 15-min refresh | Free, no auth, 20 req/min; verified live | **Strong add** — redundancy for the ApeWisdom SPOF + the missing direction |
| **FINRA daily short-sale volume** | Per-symbol daily ShortVolume/TotalVolume (CDN text files); bi-monthly short interest API also open | Free, no auth; verified | **Strong add** — daily cadence matches the bot |
| **SEC EDGAR full-text search** | 8-K material-event tripwires by phrase per watchlist ticker | Free, UA header; verified | **Strong add** — near-zero lift on existing EDGAR code |
| **CBOE delayed options JSON** | Full chain w/ volume, OI, IV → put/call + UOA-lite | Free, no auth; ~1.6MB/symbol → limit to ~10 tickers/day | **Strong add** (scoped) |
| **Finnhub news** | Company headlines, 60 calls/min free | API key | **Strong add** for headline layer |
| StockTwits public API | ~70% of messages user-tagged Bullish/Bearish | No auth but Cloudflare-fronted — **must smoke-test from an Actions runner** | Marginal-to-strong |
| Reddit OAuth (PRAW) | Raw posts/comments, 100 q/min free non-commercial | Cloud-IP reliability unverified/conflicting reports | Marginal (backup) |
| SEC FTD files | Squeeze context, ~1-month lag | Free; verified | Marginal (context only) |
| Alpha Vantage / Marketaux news | Sentiment-tagged news, 25–100 req/day free | Key | Marginal |
| Google Trends (pytrends) | — archived 2025, datacenter 429s | — | **Dead** (Wikipedia pageviews is the free substitute) |
| Unusual Whales API | Options flow | ~$48+/mo, API extra | Dead for this budget |

## Product landscape — what winners ship

- **Quiver Quant** (~$25/mo): ~30 datasets; **Smart Score** composite 1–10 per ticker;
  per-ticker page aggregating everything; **named tracked strategies** with live
  performance charts (→ copy-trading). Track record is the marketing.
- **Unusual Whales** (~$48/mo): real-time flow; **latency is the paid tier**; alerts via
  push/Discord (no email/SMS); licensed congress data to real ETFs (NANC/KRUZ) — ultimate
  transparency play.
- **ApeWisdom** (our upstream): free table + open methodology page; no alerts, no
  drill-down, no scoring — exactly the gap above it.
- **SwaggyStocks**: semi-dormant — pure WSB dashboards without alerts/breadth stagnate.
- **Stocktwits**: recency-weighted sentiment; charts social volume **against price**.
- **Open-source agent wave** (TradingAgents ~80k★, ai-hedge-fund ~59k★): LLM analysts
  that *debate* the signals and emit thesis + confidence + decision-shaped output — the
  2025–26 differentiator over sorted tables.

**Recurring winner patterns**: composite score w/ visible components · per-ticker
drill-down · published live track record w/ honest disclaimers · per-politician/insider
profile pages · latency tiering · user-defined alert filters · methodology page ·
agent layer on top.

## Follow-up research (owner-requested, verified 2026-08-07)

- **Unusual Whales public API**: **no free tier.** The $0 web tier excludes API access;
  pricing (effective 2025-05-27, still current): $50/wk trial, Basic $150/mo, Advanced
  $375/mo, +$250/mo for full historical option tape. Congress + flow endpoints exist but
  only paid. **Skip** — free sources already cover congress/insider.
- **Inverse Cramer**: feasible at **$0**. SJIM ETF confirmed liquidated 2024-02-23.
  Primary source: GitHub `jf-silverman/analyzing-stock-calls` — nightly pipeline
  committing `data/stock_sentiments.json` (per-ticker Mad Money mentions w/ date,
  sentiment enum `strong_buy`…`sell_avoid`, segment incl. `lightning_round`); fetchable
  keyless via raw.githubusercontent.com, entries fresh to 2026-08-04. Caveat: third-party
  hobby repo, LLM-transcribed — pin commits, vendor snapshots, fail-soft. Cross-check:
  Quiver's `cramertracker` page (maintained, picks dated 2026-07-29) is server-rendered
  and scrapeable (ToS gray zone); its API tiers do NOT include Cramer data.
- **Newsletter-class**: Stocktwits legacy endpoints (`trending/symbols.json`, symbol
  streams w/ ~70% user-tagged bull/bear) return 200 unauthenticated but are
  Cloudflare-fronted → **must smoke-test from a real Actions runner**. Substack RSS
  (`{name}.substack.com/feed`) verified working — marginal, needs curation of pick-heavy
  letters. Google News RSS per ticker: free mention-count proxy, marginal. **Dead**: Yahoo
  trending (429s datacenter IPs), Finviz (Elite-only export), StockAnalysis.com (no API),
  WSB daily-thread JSON (cloud 403).

## PR #4 re-review (2026-08-07)

Still valid, still needed: top-15 board remains ~all-`hot` on live data (13/15 on
2026-08-07) with raw-5 blips aboard; neither change ever landed on main; merges cleanly
onto today's main; merged suite green (209 tests). Note: after merge, `state` in
history.json becomes board-relative for board names → backtest event study must treat the
merge date as a regime boundary. PR #3's roadmap content is superseded by main.

## Candidate directions (decision pending)

1. **Prove it + start the clocks** — nightly backtest harness (protocol above) on the
   66-day history; archive Early Plays and publish a live scorecard; ingest Tradestie
   daily so directional-sentiment history starts accruing. Cheapest; answers the
   roadmap's #1 open question; every week of delay costs a week of sample.
2. **Widen the signal** — composite per-ticker score + drill-down page; add FINRA
   short-volume, CBOE UOA-lite, 8-K tripwire, Finnhub headlines.
3. **Reason over it** — LLM analyst/debate layer over board + tripwires (thesis +
   confidence, decision-shaped output); optional paper-trading consumer downstream.
