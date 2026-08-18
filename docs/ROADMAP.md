---
project: Reddit Signal Radar
status: live — daily board + email in prod, 9-monitor fleet (Trump/EDGAR/Fed/Congress/EDGAR-8K/Dilution/Shelf/Activist/Delisting) on a 30-min tick
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
([[2026-08-17-community-mining]]). Sequenced by dependency: E1 needs no new source,
E2's sources are verified, E3 needed a CI probe (now passed), and E4 reasons over
whatever E1–E3 produce. **One spec per sub-phase**, written when the prior one lands —
not all four up front.

Live status lives in [[HANDOFF]]; this section is the shape, that doc is the state.

### E0 — Settle the cloud-IP question ✅ **done 2026-08-17**
- [x] Probed from a real Actions runner (no secrets, throwaway, since deleted).
      **StockTwits answers a cloud IP** — real JSON, not a challenge page — so E3 is
      unblocked. **Reddit RSS does not**: 429 with `x-ratelimit-remaining: 0.0` on the
      first request, because the Actions IP range shares one exhausted Reddit bucket.
      That is a different failure than the JSON path's 403, and it is not fixable by
      backing off — only by a self-hosted runner. Wikimedia / Nasdaq / FINRA / SEC FTD
      all answered 200. Full results: [[HANDOFF]] §3.

### E1 — Catalyst layer  ✅ **done 2026-08-17**
EDGAR full-text search already runs from CI; `edgar_events.py:17` just hardcodes
`&forms=8-K`. Generalize it to form classes. Measured ~3.2 alerting tickers/day at the
chosen 90-day watch gate.

- [x] **Sign the `events` composite component first.** `composite.py:43` scores any
      fresh alert as `100.0`, and `run.py:154` discards monitor identity — so a 424B5
      dilution would *raise* a ticker's composite. Blocking defect for this phase.
- [x] Form-parameterized EDGAR monitor (the EFTS `forms=` and `q=` both come from config).
- [x] Classes: `dilution` (424B5, `q="at the market offering"`), `shelf` (S-3/S-3ASR),
      `activist` (SCHEDULE 13D), `delisting` (25-NSE). Form code is `SCHEDULE 13D`, not
      `SC 13D`. Per-class `q` is the debt/equity discriminator — measured, see spec.
- [x] Widen the watch gate to the full 90-day history (654 tickers, vs 148 at 7 days).
- [x] Skip `SCHEDULE 13G` (~1,300/week) and `NT 10-Q` (~96/6d) — volume, not signal.
- [ ] **EFTS paging (or narrowing the `edgar8k` `bankruptcy` phrase).** That query alone
      returns a full 100-hit EFTS page daily (measured 127/188/197 hits, 2026-08-17,
      [[HANDOFF]] §4) — `parse_hits` only reads page 1, so roughly half those 8-Ks go
      unseen. Pre-existing, not caused by E1; the four new classes stay well under the
      cap. Paging is explicitly out of scope for this phase — this item is tracking it
      for later, not implementing it now.

### E2 — Non-social attention  ✅ **built 2026-08-17** (not yet run live)
Measurement split this sub-phase in two. **These two sources are not peers** — pageviews
are 7.5 h fresh, short interest is 11–24 days stale and twice-monthly — so they get
different tiers, not one slot. A prerequisite the plan did not see also surfaced: the
ticker→article mapping is 13.7% wrong-entity and must be fixed first.

- [x] **Decided: published-but-unweighted.** Short interest permanently (a fortnightly
      step function inside a daily composite would be misattributed by the backtest);
      `attention` until the power gate. Decisive reason: `backtest.py` computes **no
      per-component ICs**, so the "recalibrate from measured ICs" plan below has no
      measurement behind it. Full reasoning in [[HANDOFF]] §5.
- [x] **E2a — ticker→article mapping first.** Wikidata `p:P414/pq:P249`, US-scoped;
      precision 13.7% → 0.4% wrong, and it fails closed. Spec:
      [[2026-08-17-ticker-article-mapping-design]]. Built: `radar/tickermap.py`,
      `radar/ticker_overrides.yml` (30 verified entries), `radar/about.py` rewritten.
- [x] Wikimedia pageviews (keyless, verified) — the discriminator between a real story
      and a Reddit brigade, and the Google Trends replacement Phase D wanted. Scored as a
      **self-relative spike** (today vs the ticker's own 28d median), not a board-relative
      percentile — a cross-sectional rank would mostly measure market cap.
      Built: `radar/pageviews.py`.
- [x] Short **interest** + days-to-cover — **FINRA, not Nasdaq** (identical data, keyless,
      batchable; Nasdaq returned HTTP 000 on a default curl UA and is a cloud-IP-block
      risk). Distinct from the FINRA daily short *volume* already ingested: that is flow,
      this is open position. Ships as an `as_of`-stamped context field, never a component.
      Spec: [[2026-08-17-non-social-attention-design]]. Built: `radar/short_interest.py`.
- [ ] **Verify the first live run** — none of this has contacted Wikimedia or FINRA yet.
      The suite is hermetic by design, so the 6:17 AM job is the first real exercise.
- [ ] **Follow-up, blocks any future weighting:** build the per-component IC estimator in
      `backtest.py`, and correct the "a config change, not a code change" claim in
      `radar/composite.py:5`, `config.yaml:111` and `README.md:66` — it is false as
      written.

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

- **2026-08-17 (E2a + E2 built)** — Both sub-phases implemented behind the specs below.
  446 tests, 0 network calls. Three architectural notes worth carrying forward.
  **(1) Unweighted turned out to cost nothing and buy a lot.** `attention` ships in
  `components` with no entry in `composite.weights`, so `blend()`'s `weights.get(k,0) > 0`
  filter drops it: no rebalance of the existing seven, composite values bit-identical, and
  therefore **no regime boundary** — the backtest series stays comparable straight through
  this phase. Adding a weight later is a deliberate act that now trips a test.
  **(2) Every guard in this phase had to be watched failing before it counted.** Review
  found two tautological tests — one comparing a value against a string built from that
  same value, one asserting nothing — plus a guard aimed at `DEFAULT_WEIGHTS` when
  production reads `config.yaml`. The habit that caught them was mutation: break the thing
  on purpose, confirm exactly one test dies. Several defects were invisible to inspection
  and only fell out of that.
  **(3) The most dangerous failures here are all silent-success shapes**, not exceptions:
  an API returning HTTP 200 with a truncated result and a `COUNT` that agrees; a redirect
  title returning 200 with the wrong article's traffic; a health LED that cannot report
  failure; a test that reads production state and arms itself weeks later. Guards that only
  check "did it raise" would have caught none of them.
- **2026-08-17 (E2 specs + hermetic suite)** — Four measurements changed this phase from
  what the plan assumed. **(1) Pageviews and short interest are not peers.** Pageviews'
  D-1 data lands ~02:30 UTC against a 10:17 UTC publish (+7.5 h); short interest is
  twice-monthly and settlement-based at **11–24 days stale**. Bundling them into one slot
  — the plan's framing — would have put a fortnightly step function inside a daily
  composite, which the backtest would then misattribute to whichever day the step landed
  on. Specced as separate tiers: pageviews a published component, short interest an
  `as_of`-stamped context field that is never a component.
  **(2) Weighting decided: published-but-unweighted**, and the decisive reason is not the
  power gate (76/150 days) but that **`backtest.py` computes no per-component ICs at
  all** — `_frames()` emits the raw velocity score. The "recalibrate from measured ICs, a
  config change not a code change" claim in `radar/composite.py:5`, `config.yaml:111` and
  `README.md:66` is therefore false as written, and building that estimator is now a
  named prerequisite for any future weighting. Unweighted costs nothing:
  `composite.py:54` already drops keys with no weight, so there is no rebalance of the
  existing seven and **no regime boundary**.
  **(3) A prerequisite the plan did not see.** `radar/about.py` guesses the Wikipedia
  article from ApeWisdom's company name; the live cache is 59.3% populated and **13.7%
  wrong-entity** (`AAPL`→the fruit, `ADBE`→a building material, `HTZ`→the SI unit,
  `SDGR`→a dead physicist). Harmless-looking on the About modal, fatal for pageviews:
  `SDGR` would feed ~988 physics-class views/day into a biotech score whose true value is
  41, every day, invisibly. Fixed first as E2a via a Wikidata exact-title map (13.7% →
  0.4% wrong) whose key property is that it **fails closed** — `MVIS` resolves to nothing
  rather than a 1979 Milton Bradley game console, which is what fuzzy search returns.
  Scoring for pageviews is a **self-relative spike** (today vs the ticker's own 28d
  median, log2-scaled); a board-relative percentile would mostly rank market cap.
  **(4) The test suite was not hermetic and gates the publish.** 353 passed 43.95 s →
  0.95 s, 0 DNS lookups. The prior handoff entry describing this was wrong in three ways
  (named Cramer, which `run.py:138` gates behind `--dry-run`; missed Wikipedia, the larger
  caller; and named only one of the two offending test files) — corrected in [[HANDOFF]]
  §6 rather than silently replaced. Specs:
  [[2026-08-17-ticker-article-mapping-design]], [[2026-08-17-non-social-attention-design]].
- **2026-08-17 (E1 catalyst layer)** — Landed E1: signed the `events` composite
  component first (`radar/composite.py`) — `bearish 0 / neutral 50 / bullish 100`,
  `None` when no fresh alert covers the ticker — fixing the open defect where every
  component was unsigned and a 424B5 dilution would have *raised* a ticker's
  composite. Generalized the EDGAR full-text monitor to take `forms=`/`q=` from config
  instead of hardcoding `8-K`, and wired four new form classes via config's new
  `edgar_forms` list: `dilution` (424B5, "at the market offering", bearish), `shelf`
  (S-3/S-3ASR, "offering", neutral), `activist` (SCHEDULE 13D, "common stock", bullish),
  `delisting` (25-NSE, "delisting", bearish) — all four watch the full 90-day history
  (654 tickers); `edgar8k` keeps its own 7-day gate. Fleet monitor count: five → nine
  (`trump, edgar, fed, congress, edgar8k, dilution, shelf, activist, delisting`).
  Stamped a `radar/backtest.py` `regime_notes` entry dated 2026-08-17: every composite
  before/after this date is incomparable. Test suite: 351 passing (up from 327 pre-E1).
  Spec: [[2026-08-17-catalyst-layer-design]]. Commits: `c85e5a0` (monitor direction),
  `e602bce` (signed events component), `68897a7` (accession dedup), `d46ce3c` +
  `c8f094e` (form-parameterize + fix round), `de2456b` (wire the four classes). Not yet
  measured: real alert volume after 1 week live vs. the ~3.2/day estimate — see
  [[HANDOFF]] §4.
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
