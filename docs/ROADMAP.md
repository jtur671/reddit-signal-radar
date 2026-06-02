---
project: Reddit Signal Radar
status: v1.0 — built, not yet deployed
updated: 2026-06-01
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
- [ ] Bump `actions/checkout`, `actions/setup-python`, `actions/upload-pages-artifact`,
  `actions/deploy-pages` when Node-24 versions ship (GitHub forces Node 24 on 2026-06-16).

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
- [ ] **Backtest the signal** — does "high velocity + surprise" actually predict next-day price moves? Join history with price data. (This is the bridge to any trading use — but keep this project a *radar*, not a trader.)
- [ ] **Mobile-friendly dashboard pass.**

---

## Open questions

- Does the freshness signal have *predictive* value, or is it just a popularity mirror? (Phase D backtest answers this.)
- Is a daily cadence right, or does intraday matter for meme/crypto velocity?
- Keep DeepSeek for summaries, or swap to a local model to cut cost/latency and remove the external-LLM injection surface?

## Decision log

- **2026-06-01** — Built v1.0 from the plan via subagent-driven TDD. Adjudicated a plan-defect test fixture, hardened the baseline against silent-day freeze, added a per-author weight cap, fixed a detached-HEAD CI push that would have broken every run. Kept scope as a *signal radar* (publish/notify), explicitly **not** a trader. Roadmap kept separate from the `money` vault per owner.
