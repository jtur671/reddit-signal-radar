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

- [ ] **Create GitHub repo + push.** `reddit_review` is a local git repo on `main`; needs a remote.
- [ ] **Enable Pages** → Settings → Pages → Source: **GitHub Actions**.
- [ ] **Add repo secrets:** `DEEPSEEK_API_KEY`, `RESEND_API_KEY`, `EMAIL_RECIPIENTS` (optional `ALPACA_API_KEY`/`ALPACA_SECRET_KEY`).
- [ ] **Manual trigger** (Actions → daily-radar → Run workflow) to validate the *real* run before the first 6 AM cron.
- [ ] **Verify live artifacts:** dashboard renders at the Pages URL, email arrives, `data/history.json` commit-back succeeds (this is the detached-HEAD fix — confirm it actually pushes).
- [ ] **Confirm Reddit isn't blocking the Actions runner** — local env was rate-limited; GitHub IPs may differ. If empty boards persist, see Phase C (auth).

**Exit:** one successful end-to-end scheduled run with a non-empty board and a delivered email.

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
