# Reddit Signal Radar — Design Spec

**Date:** 2026-06-01
**Status:** Approved design, pending implementation plan
**Owner:** you@example.com

---

## 1. Overview

An automated, zero-touch radar for **retail trading sentiment momentum**. Every day at 6:00 AM ET it scans every relevant trading community on Reddit, finds the tickers the crowd is buzzing about, scores them for **freshness/velocity/sentiment**, enriches them with live market data, and publishes:

1. A **public infographic dashboard** (GitHub Pages) — "what's hot today" at a glance, with progressive technical depth and 90 days of trend history.
2. A **daily email** (Resend) with the top signals.

The point: wake up to a curated picture of what's heating up across the trading internet — with enough context (price, trend, sentiment, *why*) to decide what's worth a closer look.

### Non-goals
- Does **not** place trades or connect to a brokerage for execution.
- Does **not** give financial advice or guarantee signal quality.
- It is a **discovery/awareness** tool that aggregates crowd attention.

---

## 2. Architecture

**Single daily run, fully serverless, on GitHub Actions** (chosen over a local cron so it runs regardless of whether any machine is awake; chosen over an always-on VPS for zero cost/maintenance).

```
GitHub Actions (cron: 6:00 AM ET daily)
  └─ python -m radar.run
       fetch ─▶ extract ─▶ score ─▶ (sentiment + enrich) ─▶ render ─▶ publish ─▶ email
                              ▲                                          │
                       history (read)                            history (write, committed back)
```

Because Actions runners are ephemeral, the **90-day history store is committed back to the repo** at the end of each run. That history file *is* the velocity baseline and the trend-chart data source.

**Deployment:** rendered static HTML + a small JSON data file are pushed to the `gh-pages` branch (or `/docs`), served by GitHub Pages at a public URL.

---

## 3. Components

Each is a focused module in a `radar/` Python package with a single responsibility and a clean interface.

### 3.1 `fetch`
- Pulls Reddit **public `.json` endpoints** — no OAuth app, no API key. (e.g. `https://www.reddit.com/r/<sub>/hot.json?limit=100`, `.../new.json`, `.../top.json?t=day`, and `<permalink>.json` for top comments.)
- Per subreddit: hot + new + top-of-day listings; for the most-active posts, also fetch the comment tree and keep **top-level + high-score comments**.
- Custom descriptive `User-Agent`, polite rate-limiting (sleep between requests), exponential-backoff retries, and graceful skip on 429/403/5xx so one bad sub never fails the run.
- Keeps only content **created in the last ~48h** (the lookback window).
- Output: a normalized list of items `{id, kind(post|comment), subreddit, author, created_utc, text, score, permalink}`.

### 3.2 `extract`
The hardest piece: distinguishing `$GME`/`BTC` from words like "DD", "YOLO", "AI", "CEO".
- **Cashtags** (`$AAPL`, `$BTC`) — trusted outright.
- **Bare uppercase tokens** — matched against a committed **universe** of real US-listed symbols (NYSE/NASDAQ/AMEX) + top ~200 crypto symbols, then filtered through a **slang/common-word stoplist** (DD, YOLO, CEO, USA, AI, IT, FOR, ARE, PUMP, IMO, ATH, FD, OTM, ITM, EOD, CFO, IPO, ETF, …).
- **Theme name keywords** — company/colloquial names mapped to tickers (e.g. "spacex"→context, "palantir"→PLTR) from `themes.yaml`, so we catch mentions even without a cashtag.
- Output: one record per mention `{ticker, item_id, subreddit, author, created_utc, text}`.

### 3.3 `score` — the freshness engine
The core that keeps the board fresh and lets stale signals fall off. (Master tuning knob: **24h half-life**.)

For each ticker, over the 48h window:
1. **Recency-decayed weight** — each mention weighted `0.5 ^ (age_hours / 24)` (24h half-life), summed → `today_weighted`.
2. **Adaptive baseline** — an **EMA** of recent daily weighted counts from the history store. Because the EMA *adapts*, a name that stays hot for days sees its baseline climb to meet it, so it stops reading as a spike.
3. **Velocity** = `today_weighted / baseline` (the "×" multiple).
4. **Surprise (z-score)** = `(today_weighted − baseline_mean) / baseline_std` — normalized by the ticker's own historical noise. Rewards genuinely *new* attention (3 mentions on a normally-0 ticker beats 300 on GME).
5. **Noise floor** — to be eligible for the board a ticker must clear **min absolute mentions** *and* **min distinct authors** (anti-spam / anti-manipulation). Defaults: ≥ 5 mentions, ≥ 4 distinct authors (tunable).
6. **Composite score** — **surprise-weighted** (surprise dominates; absolute volume is a secondary tiebreaker), modified slightly by sentiment. Top **15** by composite become "the board."

**Lifecycle state** (drives the dashboard color system):
- 🆕 **Breaking** — high surprise, low/absent baseline (brand new).
- 🔥 **Hot** — accelerating (velocity ≫ 1, rising).
- ➡️ **Sustained** — high but flat (velocity ≈ 1, baseline caught up).
- 🧊 **Cooling** — velocity < 1 / negative surprise (falling off).

**Worked example (SPCE / SpaceX IPO):** Day 0 spikes 5→400/day → huge surprise → #1, 🆕. Days 1–3 stay ~350 → baseline EMA climbs → surprise shrinks → slides down, 🔥→➡️. Day 5–7 crowd leaves, today ~80 but baseline ~250 → below baseline → negative surprise → 🧊 → drops off top 15. No manual cleanup.

### 3.4 `sentiment`
- **Bulk:** VADER + a **finance-tuned lexicon** (moon, calls, puts, bagholder, tendies, rip, dump, squeeze, rug, etc.) scores every mention → per-ticker **% bull / % bear**.
- **Sharp summaries:** a **DeepSeek** API call (OpenAI-compatible, cheap) writes a 1–2 sentence "why it's trending" for the **top 15 only**, plus the single "Today's Read" market-mood paragraph. Bounded cost per run.

### 3.5 `enrich`
- **yfinance** as the broad primary (price, % change, volume — covers stocks + crypto + most tickers, no key).
- **Alpaca** (existing account) for stocks/crypto it covers, when available.
- Missing data degrades gracefully (show "—").

### 3.6 `history`
- A **90-day rolling JSON store** committed to the repo.
- Per ticker per day: weighted mention count, raw count, distinct authors, % bull, composite score, lifecycle state.
- Read at the start of `score` (baseline); rewritten + committed at the end of the run. Entries older than 90 days are pruned.

### 3.7 `render`
- **Jinja2** → a single static `index.html` (self-contained, the approved Mono Machine design) + a small `data.json` for the trend charts.
- Inline/CDN fonts; no build step required.

### 3.8 `publish` + `email`
- `publish`: push HTML/JSON to GitHub Pages.
- `email`: render a top-signals summary email (same visual language, email-safe HTML) and send via **Resend** to the configured recipient(s).

---

## 4. Coverage — subreddits & themes

### 4.1 Subreddit list (editable `subreddits.txt`)
Starter set across the requested domains (trimmed/expanded over time):

- **General/stocks:** wallstreetbets, stocks, StockMarket, investing, options, thetagang, smallstreetbets, Daytrading, swingtrading, RealDayTrading, wallstreetbetsOGs
- **Penny/small-cap:** pennystocks, RobinHoodPennyStocks, smallcaps
- **Value/short/squeeze:** ValueInvesting, Shortsqueeze, DeepFuckingValue, Superstonk, GME, SPACs
- **Futures:** FuturesTrading
- **Crypto:** CryptoCurrency, CryptoMarkets, SatoshiStreetBets, CryptoMoonShots, Bitcoin, ethtrader, BitcoinMarkets, altcoin
- **Biotech:** Biotechplays, biotechstocks
- (Defense/oil/AI/Trump are captured via **themes** + the broad subs rather than dedicated subs.)

### 4.2 Themes (`themes.yaml` — theme → seed tickers + name keywords)
Each surfaced ticker is tagged with one or more themes via (a) these curated seed lists, (b) name-keyword matches, and (c) yfinance sector/industry mapping.

- **AI Compute / ex-bitcoin miners** *(hard-seeded so they're watched even at low volume)*: IREN, HIVE, WULF, CORZ, APLD, CIFR, MARA, RIOT, BTDR, CLSK, BTBT, HUT, GREE, SDIG · plus AI-infra: NBIS, CRWV, SMCI, VRT
- **AI stocks:** NVDA, PLTR, AMD, AVGO, SMCI, MSFT, GOOGL, META, TSLA, BBAI, SOUN, AI
- **Crypto:** BTC, ETH, SOL, XRP, DOGE + crypto-equities COIN, MSTR, HOOD
- **Meme:** GME, AMC, MULN, KOSS, BB, DJT
- **Short squeeze:** GME, AMC + dynamic (high short-interest names by mention)
- **Bio/Pharma:** sector-mapped; seeds SAVA, MRNA, NVAX, PFE
- **Defense / war:** LMT, RTX, NOC, GD, BA, LHX, KTOS, AVAV, LDOS, PLTR, RKLB
- **Oil / energy:** XOM, CVX, OXY, COP, SLB, HAL, DVN, MPC, VLO
- **Trump-related:** DJT, PHUN, BKKT, RUM, $TRUMP
- **Space:** RKLB, ASTS, LUNR, RDW, SPCE

> **Open item:** the user mentioned "keel" as an ex-miner→AI name — unresolved (possibly KULR?). To be confirmed and hard-seeded. All seed/keyword lists are user-editable.

---

## 5. Dashboard design (approved)

**Aesthetic: "Mono Machine" — a quant/Bloomberg-style terminal.** Reference mockup: `docs/superpowers/specs/assets/dashboard-reference.html`.

- **Type:** Martian Mono (nameplate + tickers — tight, machined), JetBrains Mono (all body + data, tabular numerals).
- **Palette:** warm near-black (`#08090b`) with film-grain texture; paper-white ink; **muted** signal green (`#5fcf97`) / oxblood red (`#e0654f`); amber accent (`#e0b049`); cyan (`#63c2d4`) for cooling.
- **Lifecycle color system (consistent across Board + Cards):** 🆕/🔥 → **green** highlight (wash, ring, green heat bar); ➡️ → neutral/dim; 🧊 → cyan.

**Layout — progressive disclosure (glance → technical), top to bottom:**
1. **Masthead** — "Reddit Signal Radar", edition/date, live pulse dot.
2. **01 · The Board** — top-15 heat-tile grid + theme filter chips. *(Leads the page.)*
3. **02 · Today's Read** — terminal-window block with a `$` command line + blinking cursor, the DeepSeek market-mood paragraph, and 4 KPI tiles (signals tracked, biggest breakout, most bullish, corpus scanned).
4. **03 · The Movers** — rich signal cards (velocity / surprise / authors / sentiment bar / "why" quote / sources); Breaking & Hot cards get the green highlight.
5. **04 · The Listings** — full per-ticker metrics table (score, mentions, velocity, surprise σ, authors, % bull, price, Δ, state).
6. **05 · Archive & Method** — 90-day trend chart, "cooling off the board" list, and the scoring methodology colophon.

---

## 6. Configuration & secrets

GitHub Actions repo secrets:
- `DEEPSEEK_API_KEY` — top-15 summaries + market mood.
- `RESEND_API_KEY` — email delivery.
- `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` — market enrichment (optional; yfinance is the fallback).
- `EMAIL_RECIPIENTS` — default `you@example.com`.

Tunables (`config.yaml`): half-life (24h), lookback window (48h), noise floor (min mentions / min authors), top-N (15), history retention (90d), per-sub request caps.

---

## 7. Tech stack

Python 3. Libraries: `requests` (Reddit JSON), `vaderSentiment`, `yfinance`, `alpaca-py` (optional), `jinja2`, `pyyaml`, an OpenAI-compatible client for DeepSeek, `resend`. Charts as inline SVG (no JS framework). GitHub Actions for scheduling + Pages deploy.

---

## 8. Resilience & error handling

- Any single subreddit / post / API failure is caught and skipped; the run always produces a dashboard from whatever data succeeded.
- Reddit rate-limit (429) → backoff + reduced request budget.
- Enrichment/DeepSeek failures degrade gracefully (omit price / omit summary), never fail the run.
- History write is the last step and is idempotent for a given date (re-runs overwrite that day).

---

## 9. Testing

- **Unit:** ticker extraction (cashtag vs. stoplist vs. universe edge cases), decay math, EMA/z-score, lifecycle classification, noise-floor gating — with fixture corpora.
- **Golden:** a recorded Reddit-JSON fixture → deterministic scored output.
- **Render:** snapshot the generated HTML against the approved reference.
- **Dry-run mode:** run end-to-end without publishing/emailing (writes to a local `out/`).

---

## 10. QA, Hardening & Verification

This system is **coded once and then only viewed live** — there is little day-to-day observability to catch silent rot. So correctness, and above all **the guarantee that the board never goes stale**, is front-loaded with an aggressive QA gauntlet *after* implementation and *before* go-live.

### 10.1 The anti-staleness invariants (the things QA must prove)
These are the testable properties the freshness engine must satisfy. They are the primary target of the chaos game day:

- **INV-1 (Decay):** a ticker that receives **no new mentions** must have a strictly **decreasing** composite score each subsequent day, and must leave the top-15 within a bounded number of days.
- **INV-2 (No carry-forward):** nothing is ever summed cumulatively across days; only the EMA baseline persists. Yesterday's total can never inflate today's rank.
- **INV-3 (Baseline catch-up):** a ticker held at a constant elevated mention level must see velocity → ~1 and surprise → ~0 over time (it stops reading as a spike).
- **INV-4 (Window cutoff):** content older than the 48h lookback contributes **exactly zero** weight.
- **INV-5 (Clock correctness):** the "today" window and `age_hours` are computed correctly across UTC/ET and **DST boundaries** — a classic source of "frozen" or double-counted data.
- **INV-6 (Missed-run safety):** a skipped daily run (CI outage) must not freeze the baseline or resurrect a stale signal; gaps are handled explicitly.
- **INV-7 (Empty data):** if Reddit returns nothing, the dashboard shows "no signals today" — **never** yesterday's stale board.
- **INV-8 (Numerical safety):** baseline = 0 (velocity), std = 0 (z-score), and single-sample histories never divide-by-zero, produce NaN/Inf, or crash — they degrade to defined values.

### 10.2 Phase A — Chaos Game Day (`qa-chaos-agent`)
Run the qa-chaos skill against each module to *try to break it*, prioritized:
1. **The freshness engine first** — adversarial cases targeting INV-1…INV-8 (e.g. all-old timestamps, constant-level streams, zero/one-sample baselines, DST jumps, a ticker that mentions once then goes silent for 10 days).
2. **`extract`** — cashtag spoofing, stoplist edge cases, unicode/emoji, ALL-CAPS posts, a single spammer flooding one ticker (noise-floor must hold).
3. **`fetch`/parse** — malformed/partial Reddit JSON, deleted authors (`[deleted]`), missing fields, 429/403, empty listings, enormous comment trees.
4. **Security** — **HTML/script injection** from Reddit text must be escaped in the rendered dashboard (no stored XSS); **prompt injection** in post text must not hijack the DeepSeek summary (sanitize + instruct model to treat corpus as untrusted data).
5. **`enrich`/`render`** — unknown tickers, missing prices, NaN, very long summaries.

Output: structured findings by severity. **Fix all critical/high before proceeding.**

### 10.3 Phase B — Two rounds of code review
- **Round 1** (`requesting-code-review`): full-codebase review for correctness, the staleness invariants, security, and clarity → triage → fix.
- **Round 2:** verify Round-1 fixes landed correctly *and* do a second independent deep pass (fresh eyes) → fix.

### 10.4 Phase C — Bug bounty
A final dedicated adversarial sweep: dispatch independent agents (parallel) to hunt for any remaining correctness, staleness, or security bug across the whole system, triage findings, and fix. This is the last gate before the first live run.

### 10.5 Exit criteria (go-live)
All anti-staleness invariants have passing tests; zero open critical/high findings from chaos, both review rounds, and the bug bounty; the dry-run produces a correct dashboard from a recorded fixture; and a simulated 10-day "silent ticker" sequence demonstrably decays it off the board.

---

## 11. Open items
- Confirm "keel" ticker (KULR?) and any other must-include names to hard-seed.
- Final subreddit list pruning after first live runs (drop dead/low-signal subs).
- Email layout fidelity (email-safe HTML subset of the dashboard).
