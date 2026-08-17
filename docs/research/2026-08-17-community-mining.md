---
project: Reddit Signal Radar
topic: "Next level" round 2 — mining Reddit (RSS), GitHub, and other forums for upgrades
date: 2026-08-17
status: research notes (pre-decision)
supersedes: nothing — extends 2026-08-07-next-level.md
---

# Community Mining — Reddit / GitHub / Forums

Follow-on to [[2026-08-07-next-level]]. That pass surveyed academic evidence, the
data-source landscape, and competing products. This pass mines the *communities*:
what people are actually building and talking about, and which of those endpoints
survive a live probe today.

Everything in the tables below was **curl-verified from this host on 2026-08-17**
unless the row says otherwise. Host is residential — the cloud-IP question is called
out per row, because it is the single gate that killed the original raw-Reddit path.

---

## 0. Repo/data audit (measured 2026-08-17)

`origin/data` `history.json`: **654 tickers, 76 daily snapshots (2026-06-02 → 2026-08-17),
8,364 ticker-days.**

**Board breadth halved on 2026-08-08 — by design, not by outage.** Measured minimum
`raw` mentions per day:

| window | days | min raw | median raw | names/day |
|---|---|---|---|---|
| 2026-07-29 → 08-07 | 10 | 5 | ~12 | 101–141 (mean ~119) |
| 2026-08-08 → 08-17 | 10 | 10 | ~20 | 26–80 (mean ~54) |

That is exactly the Phase B `noise_floor.min_mentions` 5→10 raise landing. No bug. But
two consequences are real:

1. **Cross-sectional breadth for the backtest dropped ~55%.** Daily rank IC is computed
   across ~54 names now, not ~119. The `power` gate counts *days* (150 needed, 76 have),
   but thinner cross-sections widen the per-day IC error bars on top of that.
2. The 2026-08-07/08 regime boundary now marks **two** simultaneous changes (composite
   merge + noise floor), which `regime_notes` must keep distinct.

At the current rate the 150-day power gate lands around **2026-11-01**.

---

## 1. Reddit via RSS — what it actually costs

`https://www.reddit.com/r/<sub>/top/.rss?t=<window>` returns **HTTP 200** from a
residential IP, Atom, 25 entries, no auth. Measured response headers:

```
x-ratelimit-used: 1
x-ratelimit-remaining: 0.0
x-ratelimit-reset: 56
server: snooserv
```

**One request per ~60-second window, per IP, unauthenticated.** Half of a naive
10-feed burst 429'd; a 5-retry exponential backoff got everything eventually, at
roughly 1 feed/minute. Reddit's search RSS (`/search.rss?q=...`) works on the same
budget. This is *not* Cloudflare, it is Reddit's own limiter — so it is **not**
evidence the feed survives a cloud IP. Reddit's JSON 403s CI runners today; whether
`.rss` shares that block is **unverified and must be smoke-tested from an Actions
runner before any design depends on it.**

Practical read: at 1 req/min, RSS could carry a ~5-subreddit poll inside a 30-minute
fleet tick, or a ~15-subreddit sweep in the daily run. It restores **post titles and
timestamps** — raw text the ApeWisdom path threw away — but not comment bodies and
not author identity, so it does *not* solve the Phase C sockpuppet problem.

### What the subs are actually saying (mined 2026-08-17)

- **r/algotrading** — recurring theme is *prediction markets as free open data*:
  "Stop paying for Polymarket data. PMXT just open-sourced the orderbooks",
  "I built a bot to automate 'risk-free' arbitrage between Kalshi and Polymarket",
  "Built the Free All-in-One Smart-Money Tracker". Also a data-decay warning worth
  heeding: "i checked how many stocks from the old s&p 500 you can still download,
  it's bad" (survivorship bias in free price history).
- **r/Shortsqueeze** — the entire year's top-25 is **one ticker, $BYND**. Recurring
  vocabulary: *% short*, *days to cover*, *cost to borrow*, *halt*. The sub is a
  single-name echo chamber; its value to us is not breadth but that it names the
  three short-side fields the radar half-covers (we have FINRA daily short *volume*;
  we do not have short *interest*, days-to-cover, or borrow cost).
- **r/pennystocks** — catalyst-calendar culture ("Upcoming penny stock catalysts for
  July/August 2026 in Biotech and Pharma", "10 penny biotechs I'm watching"), and
  **reverse-split / dilution obsession**: "MVIS MicroVision | Reverse Split Squeeze
  Candidate", "Every week someone here asks why their stock dropped after the reverse
  split." See §3 — MVIS filed a 424B5 in the same window.
- **r/quant, r/thetagang, r/options, r/wallstreetbets** — culture and comp threads,
  near-zero signal-design content. r/wallstreetbets' top-of-month is memes and macro
  reaction. **Do not mine these for ideas**; they are the raw material, not the
  research.
- **r/webscraping** — relevant only as tradecraft: "Stop defaulting to
  Selenium/Playwright: Check the Network tab first", "Reverse-Engineering Google
  Finance", Scrapling v0.4 (auto-solves Cloudflare). Confirms the house style already
  used here (hit the JSON endpoint, don't drive a browser).
- **r/datasets** — one relevant hit: an open-source dataset of every major US layoff.

---

## 2. Other forums

| Forum | Probe | Result | Verdict |
|---|---|---|---|
| **StockTwits** `api.stocktwits.com/api/2/streams/symbol/{T}.json` | live | **HTTP 200**, 30 msgs, **11 Bullish / 5 Bearish / 14 untagged** on `$NVDA` | **Strong add** — see below |
| **StockTwits** `/api/2/trending/symbols.json` | live | **HTTP 200**, 30 symbols with `trending_score`, `watchlist_count`, `trends`, sector/industry | **Strong add** |
| Hacker News (Algolia API, keyless) | live | 200. Searched 8 finance queries, 2025+, ≥20 pts: essentially nothing. Best hit was *WARN Firehose — every US layoff notice in one searchable database* | **Skip as a ticker source**; one dataset lead |
| 4chan `/biz/` (`a.4cdn.org/biz/catalog.json`, keyless) | live | 200, 201 threads. Top caps tokens: GME 10, XMR 10, BBBY 9, BTC 8, BBBYQ 7 | **Skip** — zombie meme names + crypto, no fresh signal |
| Bluesky public appview (`public.api.bsky.app` searchPosts) | live | **HTTP 403** — needs an (free) authed session | Deferred; costs an account + token |
| Substack RSS (`{name}.substack.com/feed`) | live | 200, 520 KB | Marginal — needs hand-curation of pick-heavy letters, as in the last pass |

### The StockTwits finding is the important one

The 2026-08-07 notes rated StockTwits "marginal-to-strong — Cloudflare-fronted, must
smoke-test from an Actions runner." Measured today, the response headers are:

```
StockTwits:  server: cloudflare   cf-cache-status: DYNAMIC   set-cookie: __cf_bm=...
ApeWisdom:   server: cloudflare   cf-cache-status: DYNAMIC
```

**ApeWisdom — the radar's primary production source, running green from GitHub Actions
every day — sits behind the same Cloudflare posture.** Being CF-fronted is therefore
not disqualifying; it is the status quo. That moves StockTwits from "marginal, unknown"
to "likely works, one cheap smoke-test to confirm."

What it buys, concretely:

- **A second independent attention source.** ApeWisdom is a single point of failure;
  Tradestie is the only backup and covers WSB top-50 only.
- **Directional sentiment outside WSB.** ~53% of returned messages carry a user-applied
  Bullish/Bearish tag. The `direction` composite component is `null` for every ticker
  Tradestie doesn't cover — this fills it.
- **`watchlist_count`** — a slow-moving *stock-of-attention* number, structurally
  different from a mention *flow*. That is a new axis, not a correlated copy of velocity.

---

## 3. GitHub — projects to mine

### 3a. The highest-value idea: EDGAR form-class tripwires

The radar already runs EDGAR full-text search (`radar/monitors/edgar_events.py`), but
the query template **hardcodes `&forms=8-K`**. The endpoint takes any form code.
Measured over **2026-08-10→14 (Mon–Fri, 5 trading days)** — an earlier probe used a
Fri–Sun window and badly understated these; weekend days are near-empty:

| Form | What it means | Filings / 5 trading days |
|---|---|---|
| **424B5** | ATM / shelf takedown — *dilution actually happening* | **144** |
| **S-3 / S-3ASR** | Shelf registration — dilution being *set up* | **55 / 48** |
| **SCHEDULE 13D** | Activist accumulates >5% | **135** |
| SCHEDULE 13G | Passive >5% | ~1,300 — too noisy, skip |
| **25-NSE** | Exchange delisting notice | 2 |
| NT 10-Q | Late filing — distress | 96 (6d) — noisy |

Two mechanics to build against:

- The form code is **`SCHEDULE 13D`**, not `SC 13D` (the latter returns 0 hits). The
  `form_filter` aggregation on an unfiltered query enumerates the whole taxonomy.
- **EFTS returns at most 100 hits per page.** The busiest classes (424B5, 13D) exceed
  that in a 5-day window, so anything derived from page 1 alone is a lower bound.

#### The `q` phrase is the debt/equity discriminator

The first cut of this idea was contaminated: with `q="offering"`, the 424B5 hits
intersecting our history were **AMD, IBM, INTC, ICE, UPS** — investment-grade *bond*
shelf takedowns, not equity dilution. Scoring those as a dilution catalyst would be
straightforwardly wrong. Measured 424B5 over the same 5 trading days:

| `q` phrase | Filings | Tickers ∩ 90-day history | Megacap debt noise |
|---|---|---|---|
| `offering` | 144 | AMD, CD, EU, IBM, ICE, INTC, OTLK, REPL, RKLB, SMR, UPS | **5** |
| `shares of common stock` | 79 | ICE, INTC, MLM, OTLK, REPL, RKLB, SMR, UPS | 3 |
| **`at the market offering`** | **46** | **EU, OTLK, REPL, RKLB, SMR** | **0** |
| `at-the-market` | 70 | EU, MLM, OTLK, REPL, RKLB, SMR | 0 |
| `notes due` | 73 | AMD, EU, IBM, ICE, MLM, RKLB, UPS | 4 (by design) |

`"at the market offering"` cleanly isolates small/mid-cap equity ATMs; `"notes due"`
cleanly isolates the debt takedowns. **The phrase does the work — no market-cap or
price filter is needed.** This also means each form class wants its own tuned `q`, not
a shared one.

#### Measured alert volume (the thing that decides whether this is livable)

Unique tickers that would have alerted over 2026-08-10→14, intersecting the real
`history.json` watch sets (90-day = 654 tickers, 7-day = 148):

| Gate | Unique tickers / 5 days | Per day |
|---|---|---|
| **90-day history (chosen)** | 16 | **~3.2** |
| 7-day history (status quo) | 6 | ~1.2 |

~3 alerts/day is livable, and that is with the noisy `q="offering"` variant; the tuned
phrases cut it further. Note `REPL` appeared in **424B5, S-3ASR *and* SCHEDULE 13D**
inside one week — dilution and an activist stake on the same name. Co-occurrence across
form classes looks like a stronger signal than any single class, and is worth a look
once the classes exist.

**Live cross-validation.** The 424B5 probe surfaced **MICROVISION (MVIS)** filing on
2026-08-13. Independently, r/pennystocks' top-of-month includes *"MVIS MicroVision |
Reverse Split Squeeze Candidate."* Retail hype and an active dilution takedown on the
same name, in the same week — the exact pattern the radar exists to catch and currently
cannot see.

**But it would not have fired.** `MVIS` is **absent from `history.json` entirely**, and
`EdgarEventsMonitor` gates alerts on `active_tickers()` (names with history activity in
the trailing 7 days — 148 tickers today vs. 654 in the full 90-day window). A dilution
tripwire is most valuable precisely on the name Reddit is *about to* discover — which
argues the form-class monitors want a wider gate than the 8-K monitor uses.

#### Blocker: the `events` composite component is unsigned

`radar/composite.py:43` scores the component as:

```python
"events": 100.0 if s.ticker in alert_tickers else 0.0,
```

and `radar/run.py:154` builds `alert_tickers` as a **flat set across every monitor** —
monitor identity is discarded. Every other component in the blend is oriented so that
*higher is more interesting to a buyer*: `direction` is Tradestie's bullish share,
`cramer_inverse` maps `strong_buy`→0 and `sell_avoid`→100, `short_pressure` rises with
squeeze potential. So `events` today means "something happened, and that is bullish."

That is already loose (an insider buy and a bankruptcy 8-K score identically), but the
catalyst layer makes it actively wrong: **424B5 dilution and a 25-NSE delisting notice
would push a ticker's composite *up* by 10 weighted points.** The radar would rank a
diluting company higher for diluting.

This must be settled before 3a ships. Sketch: give each monitor a `direction` attribute
(`bullish` / `bearish` / `neutral`), map to `100 / 0 / 50`, and take the most extreme
fresh alert per ticker. Costs one field on the Monitor protocol and leaves the weight
untouched — no recalibration debt.

### 3b. Feeds and libraries worth mining

| Repo / service | ★ | Last push | Why it matters here |
|---|---|---|---|
| [`dgunning/edgartools`](https://github.com/dgunning/edgartools) | 2,592 | 2026-08-15 | Typed MIT EDGAR client — 8-K, Form 3/4/5, 13F, XBRL. Would replace hand-rolled parsing in `radar/monitors/edgar*.py` |
| [FilingFirehose](https://filingfirehose.com) | — | active | Free forensic risk score 0–100/ticker; **body-text-classified 8-Ks flagging buried events (~7.3% of Item 8.01)**, 13D/G with activist filers auto-tagged, **S-3/424B5 ATM detection**. OSS classifier: [`jaablon/buried-events-parser`](https://github.com/jaablon/buried-events-parser) |
| [`kadoa-org/congress-trading-monitor`](https://github.com/kadoa-org/congress-trading-monitor) | 119 | 2026-08-16 | **Already our congress feed** — confirmed alive and pushed yesterday |
| [`api-evangelist/bargo-congress-trades-api`](https://github.com/api-evangelist/bargo-congress-trades-api) | 0 | 2026-08-16 | Free JSON REST + MCP normalizing House **and** Senate STOCK Act. Redundancy for the kadoa SPOF |
| AlphaSMO (`alphasmo/alphasmo-tools`) | — | — | 13F + Form 4 + "smart money convergence" (funds *and* insiders buying). Free anonymous tier |
| [`TauricResearch/TradingAgents`](https://github.com/TauricResearch/TradingAgents) | 98,627 | 2026-07-18 | The agent-debate architecture. Still the reference implementation for direction 3 |
| [`virattt/ai-hedge-fund`](https://github.com/virattt/ai-hedge-fund) | 62,915 | 2026-08-07 | Ditto, persona-analyst flavor |
| [`wilsonfreitas/awesome-quant`](https://github.com/wilsonfreitas/awesome-quant) | 28,909 | 2026-08-17 | Now carries a **Prediction Markets** section — the landscape shifted since June |
| [`pmxt-dev/pmxt`](https://github.com/pmxt-dev/pmxt) | — | active | "CCXT for prediction markets" — unified Polymarket + Kalshi |

Note the *pattern* worth institutionalizing: the two feeds already in production
(`cramer`, `congress`) are both **third-party GitHub repos publishing dated JSON via
raw.githubusercontent.com**, vendored to the data branch to survive upstream death.
That pattern is cheap and repeatable; the AlphaSMO / bargo entries above are the next
two candidates.

---

## 4. New keyless endpoints verified today

| Endpoint | Result | What it adds |
|---|---|---|
| Wikimedia pageviews REST (`/metrics/pageviews/per-article/en.wikipedia/...`) | **200**, 16 daily points for `GameStop` | **Non-social attention.** The discriminator between "a real story" and "a Reddit brigade" — pageviews rise on both, Reddit rises on only one. Keyless, no rate pain, and the Google Trends replacement the last pass flagged as needed |
| SEC FTD (`sec.gov/files/data/fails-deliver-data/cnsfails*.zip`) | **200** (1.65 MB) with a contact UA; **403** without | Squeeze context, ~1-month lag |
| Nasdaq `api.nasdaq.com/api/quote/{T}/short-interest` | **200** | **Bi-monthly short interest + days-to-cover** — the fields r/Shortsqueeze actually argues about, which FINRA Reg SHO daily *volume* does not give |
| FINRA `api.finra.org/data/group/otcMarket/name/consolidatedShortInterest` | **200**, CSV, keyless | Same fields, official source, bulk |
| Polymarket Gamma (`gamma-api.polymarket.com/markets`) | **200** | Event probabilities |
| Kalshi (`api.elections.kalshi.com/trade-api/v2/markets`) | **200** | Event probabilities |
| SEC submissions (`data.sec.gov/submissions/CIK*.json`) | **200** | Per-company filing index |

On prediction markets: both APIs are open and free, and the community is clearly
excited. But mapping an event market to a *ticker* is the hard, unsolved part — the
liquid markets are macro (Fed, elections), which maps to SPY/TLT/IWM/GLD, i.e. exactly
what the Fed monitor already covers. **Interesting, not yet actionable.** Recorded, not
recommended.

---

## 5. What this pass changes vs. 2026-08-07

**Upgraded:**
- StockTwits: *marginal, CF-risk unknown* → **likely-works**, because ApeWisdom proves
  the same CF posture runs green in CI daily. One smoke-test to confirm.
- Reddit raw text: *dead (403)* → **RSS is a live path at 1 req/min from residential**;
  cloud-IP status still unverified.

**New, not in the last pass:**
- EDGAR **form-class** tripwires (424B5 / S-3 / SCHEDULE 13D / 25-NSE) — near-zero lift
  on existing plumbing, and the highest-salience catalysts for exactly the small/meme
  names the board carries. Cross-validated live on MVIS.
- Wikipedia pageviews as the **non-social attention** cross-check.
- Nasdaq / FINRA **short interest + days-to-cover** (distinct from the daily short
  *volume* already ingested).
- The `active_tickers()` gate is too narrow for catalyst monitors — measured, not
  assumed (MVIS absent from a 654-ticker history).

**Confirmed dead or skipped:** 4chan /biz/, Hacker News as a ticker source, Bluesky
without auth, SCHEDULE 13G (volume), NT 10-Q (volume).

## 6. Decisions taken and questions still open

**Decided 2026-08-17 (owner):**
- All four directions are in scope, sequenced as Phase E in [[ROADMAP]]: catalyst layer →
  non-social attention → second attention source → agent layer.
- Spec and ship **3a first**, then design the rest with the probe result and real alert
  volume in hand. One spec per phase, not one spec for all four.
- Catalyst monitors watch the **full 90-day history** (654 tickers), not the 7-day
  active set. Measured cost: ~3.2 alerting tickers/day vs ~1.2.
- The cloud-IP question gets a throwaway CI probe **before** anything depends on it —
  `.github/workflows/probe-sources.yml`, no secrets, `workflow_dispatch` only.

**Still open:**
1. **Does StockTwits answer from a GitHub Actions runner?** Blocks 3c. The probe
   answers it.
2. **Does `www.reddit.com/*.rss` answer from a GitHub Actions runner?** Reddit's own
   limiter (1/min) is separate from — and tells us nothing about — the cloud-IP block
   that killed the JSON path. The probe answers it.
3. **Signed `events` component** (§3a) — must be settled inside 3a, since 3a is what
   makes it wrong.
4. Breadth vs. floor: is ~54 names/day the right board, given the backtest needs
   cross-sectional width and the power gate is ~74 days out? Lowering `min_mentions`
   back toward 5 would restore breadth but re-admit the micro-blips Phase B removed —
   and would create a *third* regime boundary in the backtest.
5. Does cross-class co-occurrence (REPL: 424B5 + S-3ASR + 13D in one week) beat any
   single form class? Cheap to test once the classes exist.
