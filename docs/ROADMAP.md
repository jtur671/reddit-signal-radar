---
project: Reddit Signal Radar
status: live — daily board + email in prod, 5-monitor fleet (Trump/EDGAR/Fed/Congress/EDGAR-8K) on a 30-min tick
updated: 2026-08-17
tags: [roadmap, reddit-signal-radar]
---

# Reddit Signal Radar — Roadmap

> Daily zero-touch bot: scans trading subreddits → scores tickers for freshness so stale
> signals decay off the board → publishes a dashboard (GitHub Pages) + email at 6 AM ET.
> Plan: [[2026-06-01-reddit-signal-radar]] · Spec: [[2026-06-01-reddit-signal-radar-design]]

## Where it stands

- ✅ **v1.0 built** — full pipeline, 56 tests passing, INV-1..INV-8 anti-staleness gauntlet green.
- ✅ KEEL / `infrastructure` theme wired end-to-end.
- ✅ Survived chaos game day + 3-way bug bounty + final review (CI push + email resilience fixed).
- ⛔ **Not deployed** — no GitHub remote, Pages not enabled, no secrets set, never run against live Reddit.

The single most valuable next move is **GO LIVE** — everything else is enhancement.

---

## Phase A — Ship it (this week)

The bot is useless until it runs daily on real data. Blockers, in order:

- [x] **Create GitHub repo + push.** Public repo `jtur671/reddit-signal-radar`, clean
  single-commit history (neutral `radar-dev` author, all personal info scrubbed,
  secrets-detector GO). _Done 2026-06-01._
- [x] **Enable Pages** → source GitHub Actions. Live: https://jtur671.github.io/reddit-signal-radar/
- [ ] **Add repo secrets:** `DEEPSEEK_API_KEY`, `RESEND_API_KEY`, `EMAIL_RECIPIENTS` (optional `ALPACA_API_KEY`/`ALPACA_SECRET_KEY`). _Owner sets these via `gh secret set` (not via chat)._
- [x] **Manual trigger** — validation run `26796498453` succeeded end-to-end (2m34s).
- [x] **Verify live artifacts:** dashboard renders (HTTP 200); **history commit-back works**
  (detached-HEAD fix confirmed in real CI — correctly a no-op on an empty board); Pages deploy ✓.
- [x] ✅ **RESOLVED — Reddit 403 blocker → switched to ApeWisdom.** Reddit's public JSON
  403s cloud IPs (confirmed even the user's other WSB bot uses the same now-blocked
  method; the Reddit OAuth script-app path is dead post-2023). Swapped the data source to
  the free, no-auth **ApeWisdom** aggregator (`apewisdom.io`), which serves per-ticker
  Reddit mention counts + upvotes and works from cloud IPs. The freshness engine +
  anti-staleness invariants are unchanged; sentiment became an upvotes engagement proxy.
- [x] ✅ **Live populated board** — CI run produced a real 15-name board (SPCE, HPE, MU,
  NVDA, …) on the Pages site, and committed a **206-ticker** `data/history.json` back.

**Exit:** ✅ Non-empty board live and history persisting. _Email pending secrets (below)._

### Node deprecation (minor, non-blocking)
- [x] Bump `actions/checkout`, `actions/setup-python`, `actions/upload-pages-artifact`,
  `actions/deploy-pages` when Node-24 versions ship (GitHub forces Node 24 on 2026-06-16).
  _Done — workflows now on `checkout@v5` / `setup-python@v6` / `upload-pages-artifact@v5`
  / `deploy-pages@v5`._

## Phase B — Trust the signal (weeks 1–2 after live)

Watch it run, then tune from real output:

- [ ] **Baseline burn-in.** Velocity/surprise are meaningless until ~1–2 weeks of `history.json` exists. Treat early boards as "new"-heavy and don't over-react.
- [ ] **Tune the noise floor.** Real subreddit volume may make `min_mentions: 5` / `min_distinct_authors: 4` too loose or too tight — adjust in `config.yaml` from observed false positives/negatives.
- [ ] **Stoplist gardening.** Log which barewords trend; add any new common-word false positives (the prose-pollution class — e.g. words we missed beyond `SO`/`GO`/`ON`).
- [ ] **Watch KEEL + your watchlist** specifically — confirm the themes you care about surface correctly.
- [ ] **Lifecycle-label audit** (review Finding 3): does `classify_state` order `new/hot/sustained/cooling` sensibly on real data? Re-order branches if labels feel wrong.

## Phase C — Harden against manipulation (month 1+)

The known residuals, in priority order:

- [ ] **Sockpuppet brigades.** Per-author weight cap stops a lone whale, but N throwaway accounts each posting once still inflate distinct-author counts. Mitigations to evaluate: account-age/karma gating (needs authenticated Reddit API), burst-timing detection, cross-ticker stuffing detection.
- [ ] **Authenticated Reddit API.** Move off unauthenticated public JSON → OAuth app for higher rate limits, more reliable fetches, and the karma/age signals above.
- [ ] **LLM summary integrity.** Sanitizer is best-effort denylist; consider structured output + an output validator that rejects markup/instructions, and/or a cheaper local model for the bulk pass.

## Phase D — Make it more useful (backlog, unordered)

- [ ] **Per-ticker history pages / sparklines** — the dashboard `trend` polyline is currently a constant; wire it to real 90-day history per signal.
- [ ] **Theme/board filtering** that actually works client-side (theme chips are present but static).
- [ ] **Alerting on big breakouts** — push/email a mid-day flash when a ticker crosses a velocity/surprise threshold, not just the 6 AM digest.
- [ ] **Crypto coverage check** — verify crypto tickers ($BTC/$ETH/…) score well given 24/7 markets vs the daily cadence.
- [x] **Backtest the signal** — does "high velocity + surprise" actually predict next-day price moves? Join history with price data. (This is the bridge to any trading use — but keep this project a *radar*, not a trader.) _Done 2026-08-07 — weekly `radar/backtest.py` → `backtest.json`; see decision log._
- [ ] **Mobile-friendly dashboard pass.**

---

## Phase E — Deepen the signal (2026-08-17 → )

Four sub-phases from the community-mining pass
([[2026-08-17-community-mining]]). Sequenced by dependency: 3a needs nothing new,
3c is blocked on a CI probe, 3d reasons over whatever 3a–3c produce. **One spec per
sub-phase**, written when the prior one lands — not all four up front.

Live status lives in [[HANDOFF]]; this section is the shape, that doc is the state.

### E0 — Settle the cloud-IP question ✅ **done 2026-08-17**
- [x] Probed from a real Actions runner (no secrets, throwaway, since deleted).
      **StockTwits answers a cloud IP** — real JSON, not a challenge page — so E3 is
      unblocked. **Reddit RSS does not**: 429 with `x-ratelimit-remaining: 0.0` on the
      first request, because the Actions IP range shares one exhausted Reddit bucket.
      That is a different failure than the JSON path's 403, and it is not fixable by
      backing off — only by a self-hosted runner. Wikimedia / Nasdaq / FINRA / SEC FTD
      all answered 200. Full results: [[HANDOFF]] §3.

### E1 — Catalyst layer  ← **next**
EDGAR full-text search already runs from CI; `edgar_events.py:17` just hardcodes
`&forms=8-K`. Generalize it to form classes. Measured ~3.2 alerting tickers/day at the
chosen 90-day watch gate.

- [ ] **Sign the `events` composite component first.** `composite.py:43` scores any
      fresh alert as `100.0`, and `run.py:154` discards monitor identity — so a 424B5
      dilution would *raise* a ticker's composite. Blocking defect for this phase.
- [ ] Form-parameterized EDGAR monitor (the EFTS `forms=` and `q=` both come from config).
- [ ] Classes: `dilution` (424B5, `q="at the market offering"`), `shelf` (S-3/S-3ASR),
      `activist` (SCHEDULE 13D), `delisting` (25-NSE). Form code is `SCHEDULE 13D`, not
      `SC 13D`. Per-class `q` is the debt/equity discriminator — measured, see spec.
- [ ] Widen the watch gate to the full 90-day history (654 tickers, vs 148 at 7 days).
- [ ] Skip `SCHEDULE 13G` (~1,300/week) and `NT 10-Q` (~96/6d) — volume, not signal.

### E2 — Non-social attention
- [ ] Wikimedia pageviews (keyless, verified) — the discriminator between a real story
      and a Reddit brigade, and the Google Trends replacement Phase D wanted.
- [ ] Short **interest** + days-to-cover (Nasdaq and/or FINRA, both keyless, verified) —
      distinct from the FINRA daily short *volume* already ingested.
- [ ] Decide: new composite components (new heuristic weights, more recalibration debt)
      or published-but-unweighted until the power gate opens.

### E3 — Second attention source  *(unblocked 2026-08-17)*
- [ ] StockTwits ingest — an ApeWisdom-independent board source, directional bull/bear
      outside Tradestie's WSB-only coverage, and `watchlist_count` as an attention-*stock*
      axis rather than another flow.
- [ ] ~~Reddit RSS as a raw-text path~~ — **dead from CI** (E0). Only a self-hosted
      runner could revive it; not worth it for post titles alone.

### E4 — Reason over it (agent layer)
- [ ] LLM analyst/debate layer over board + tripwires (thesis + confidence,
      decision-shaped), TradingAgents-style. Last, because it reasons over E1–E3 output —
      and it partly dissolves the weighting problem, since an agent reading `components`
      doesn't need calibrated weights the way a single blended number does.

---

## Open questions

- Does the freshness signal have *predictive* value, or is it just a popularity mirror? (Phase D backtest answers this.)
- Is a daily cadence right, or does intraday matter for meme/crypto velocity?
- Keep DeepSeek for summaries, or swap to a local model to cut cost/latency and remove the external-LLM injection surface?

## Decision log

- **2026-08-17 (community mining)** — Mined Reddit (RSS), GitHub and other forums for
  the next upgrade; notes in [[2026-08-17-community-mining]], live state in [[HANDOFF]].
  Owner took all four candidate directions, sequenced as **Phase E** above, one spec per
  sub-phase rather than one spec for all four. Catalyst monitors will watch the **full
  90-day history** (654 tickers), not the 7-day active set (148) — measured cost ~3.2
  alerting tickers/day vs ~1.2, and the motivating case (MVIS: a live 424B5 the same
  week r/pennystocks called it a reverse-split squeeze) is invisible to the narrow gate.
  Three measured facts changed the plan: EDGAR full-text search accepts any `forms=`
  code (the monitor merely hardcodes `8-K`) and the `q` phrase — not a market-cap
  filter — separates equity ATMs from investment-grade debt takedowns; StockTwits sits
  behind the *same* Cloudflare posture as ApeWisdom, which runs green from CI daily, so
  it is no longer "marginal"; and `composite.py:43`'s `events` component is unsigned, so
  the catalyst layer would score dilution as bullish unless signed first. Also recorded,
  not acted on: board breadth halved on 2026-08-08 (min raw mentions 5→10, the Phase B
  floor landing as designed) — names/day fell ~119→~54, thinning the backtest's
  cross-sections while the 150-day power gate is still ~74 days out (≈2026-11-01).
- **2026-08-07 (widen phase 2)** — Widened the signal with five independent sources,
  each fail-soft with its own `health.json` check: FINRA Reg SHO daily short-sale volume
  (`radar/shorts.py` → `short_ratio` for every covered ticker), CBOE delayed options
  chains (`radar/options.py` → `pc_ratio` + a coarse `uoa` flag, top-10 board movers
  only), an EDGAR full-text 8-K tripwire (`radar/monitors/edgar_events.py`, fleet
  monitor #5 `edgar8k`, alerting only when the filer maps to a recently-active history
  ticker), inverse-Cramer sentiment (`radar/cramer.py`, vendoring a dated snapshot to
  `data/cramer_snapshot.json` on the data branch so the signal survives the upstream
  hobby repo disappearing), and Finnhub headlines (`radar/news.py`, primary when
  `FINNHUB_API_KEY` is set, falling back to the existing Google News RSS search).
  Landed a transparent composite score (`radar/composite.py`): `data.json` now carries a
  `signals` array (composite 0–100 + a `components` breakdown, each 0–100 or `null`) and
  the `weights` actually used, blended from `config.yaml`'s heuristic
  `composite.weights` with null-component renormalization — recalibrated from measured
  ICs once `backtest.json`'s `power.sufficient` turns true (a config change, not a code
  change). Two sanctioned deviations from the original spec: the `events` component
  generalizes "8-K hits in 24h" to fresh-alert involvement across *all* fleet monitors
  (cheaper, reuses existing plumbing, strictly more information), and Finnhub is
  primary-with-fallback rather than an additional feed (avoids doubling network time per
  ticker). No open Phase C/D item is superseded — this is new backlog, not a rework of
  a listed one. Spec: [[2026-08-07-measure-and-widen-design]].
- **2026-08-07 (measure phase 1)** — Built the measurement layer: free, keyless
  **Tradestie** WSB sentiment (`ts_bull`/`ts_comments` on covered tickers, plus a
  partial-board fallback when ApeWisdom is empty), an append-only `data/plays_log.json`
  track record for Early Plays picks with a daily "Early Plays Track Record" scorecard
  on the board when picks exist, and `health.json`'s new `sources` block
  (`apewisdom`/`tradestie`: `ok`/`down`/`fallback`). Added a weekly `backtest.yml` job
  (`radar/backtest.py` → `data/backtest.json`, copied to `out/backtest.json` daily):
  quintile forward excess returns vs SPY/IWM, daily rank IC with Newey-West t-stats, a
  hot-transition event study, a forward-volatility quintile test, the Early Plays
  scorecard, `price_coverage`, a `power` gate (needs 150 days; ~66 so far), and dated
  `regime_notes`. Pricing is look-ahead-safe by construction — every window starts at
  the first trading day strictly after the signal day — and the weekly job fails loudly
  on a price-fetch error rather than overwrite the last good artifact. Spec:
  [[2026-08-07-measure-and-widen-design]].
- **2026-08-07 (infra hardening)** — Tests now gate CI (`test.yml` on push/PR plus a
  pytest gate before the daily publish). The run self-assesses via `radar/health.py`:
  `out/health.json` + a `health` block in `data.json` (`ok`/`degraded`/`severe`) so
  consumers can gate on board quality, and severe degradation emails an alert — a
  degraded board can never ship silently again. Bot state commits moved off main to an
  orphan `data` branch (workflows overlay it at checkout and push state back;
  `scripts/seed_data_branch.sh` seeds/refreshes it). Dropped the long-confirmed
  `EDGAR_DEBUG` flag. **Scope decision:** the board — including Early Plays — is
  consumed by downstream trader agents, so `recommend_buys` is deliberately in scope
  as machine-consumable input; the radar itself still never places orders.
- **2026-08-07** — Diagnosed and fixed a silent week-long enrichment outage: a yfinance
  API change blanked every price and a stale `DEEPSEEK_API_KEY` CI secret killed every
  summary, and the fail-soft `except` blocks swallowed both without a word. Upgraded and
  exact-pinned yfinance (1.5.2), refreshed the secret, and added `radar/degrade.warn` so
  every degraded enrichment now leaves a `DEGRADED:` line in the CI log. Follow-up
  review pass: made `warn` genuinely never-raise, kept `0.0` as a real price, made
  `enrich` generator-safe, and routed all five DeepSeek call sites through one shared
  `_deepseek_call` helper.
- **2026-06-26** — Monitor fleet: generalized the one-off Trump tripwire into a
  `radar/monitors/` framework (`ProseMonitor` for RSS-text → ticker → DeepSeek gate,
  `EdgarMonitor` for structured filings) with a shared `run_fleet()` runner; re-homed
  Trump onto it, added EDGAR insider-buy, Fed/FOMC, and Congress STOCK Act monitors,
  and replaced `trump-monitor.yml` with `fleet-monitor.yml`. Spec:
  [[2026-06-26-monitor-fleet-design]].
- **2026-06-03** — Email redesign (branded Gmail-safe HTML, top-3 mover cards, ticker
  chips on alerts) and the "Still Running" lane (recently-broken-out names that fell
  off the top-15 stay visible while still elevated). Specs:
  [[2026-06-03-email-redesign-design]], [[2026-06-03-still-running-lane-design]].
- **2026-06-01** — Built v1.0 from the plan via subagent-driven TDD. Adjudicated a plan-defect test fixture, hardened the baseline against silent-day freeze, added a per-author weight cap, fixed a detached-HEAD CI push that would have broken every run. Kept scope as a *signal radar* (publish/notify), explicitly **not** a trader. Roadmap kept separate from the `money` vault per owner.

## Shipped 2026-06-02 (UI sprint + Trump monitor)

- Real 24h velocity (mentions vs yesterday) replacing the meaningless cold-start 99.9×.
- Today's Read is now per-category (top signal of each tracked theme), never blank.
- Theme filter chips work (client-side); tiles/cards/rows clickable → detail modal + 90-day sparkline.
- NEW: Trump Truth Social monitor (trumpstruth.org RSS, every 30 min) → red alert card + instant email when he names a ticker/company. Verified live on a real Fannie Mae/Freddie Mac post.
