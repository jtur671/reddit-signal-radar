---
project: Reddit Signal Radar
status: live (4-monitor fleet) — tuning the core signal (Phase B)
updated: 2026-06-26
tags: [roadmap, reddit-signal-radar]
---

# Reddit Signal Radar — Roadmap

> Daily zero-touch bot: ranks tickers by **freshness** so stale signals decay off the board →
> publishes a dashboard (GitHub Pages) + a 6 AM ET email. Plus a **fleet of real-time tripwire
> monitors** (Trump, SEC insider buys, Fed/FOMC, Congress) on an every-30-min cadence.
> Plan: [[2026-06-01-reddit-signal-radar]] · Spec: [[2026-06-26-monitor-fleet-design]]

## Where it stands (2026-06-26)

- ✅ **Live & deployed.** Daily radar + the every-30-min `fleet-monitor` job both running in CI.
- ✅ **v1.0 core** — freshness engine, 90-day EMA baseline, INV-1..INV-8 anti-staleness gauntlet.
- ✅ **Monitor fleet shipped** (below) — Trump + EDGAR + Fed + Congress on a reusable framework.
- ⏳ **The core signal is live but UNTUNED on real data** — that's Phase B, now active.

The single most valuable next move is **Phase B: trust the signal**. The lifecycle labels and
noise floor were set before the ApeWisdom switch, and the real board shows they need tuning.

---

## Shipped — Monitor Fleet (2026-06-26)

Generalized the one-off Trump tripwire into a reusable `radar/monitors/` framework (Signal/
Monitor contract + `run_fleet`) with two detector families (prose + structured), then added
three new monitors. All verified against live data. PRs #1 + #2 merged.

- **Trump** (prose) — re-homed onto the framework, zero behavior change.
- **EDGAR insider buys** (structured) — market-wide Form-4 purchases ≥ $1M; resolves the real
  filing doc via SEC `index.json`. Verified live in CI.
- **Fed / FOMC** (event) — every monetary-policy release, tagged SPY/TLT/IWM/GLD.
- **Congress** (structured) — STOCK Act purchases by curated notable members (Pelosi et al.) or
  ≥ $250k, from a free no-auth feed. Verified live (surfaced Pelosi's $1M–5M INTC buy).
- Multi-card dashboard (globs `data/*_alert.json`) + generalized alert email; `fleet-monitor.yml`
  runs the whole fleet, one conditional rebuild.
- Deferred follow-ons: Musk / other figures (needs a free feed), EDGAR 8-K / 13-D, Congress sells.

---

## Phase A — Ship it ✅ DONE

Live in CI; history persisting; fleet running. (The 6 AM email needs `RESEND_API_KEY` /
`EMAIL_RECIPIENTS` repo secrets set — owner action, verify it's firing.)

## Phase B — Trust the signal 🎯 ACTIVE

> **Reframed for the ApeWisdom data source.** The original Phase B was written for the raw-Reddit
> path. The live path is ApeWisdom (`radar/score.py:score_aggregates`), where the only noise-floor
> knob that applies is `min_mentions` — the **distinct-authors floor, per-author whale cap, and
> stoplist gardening are N/A live** (they only touch the still-tested raw-Reddit `score_signals`).

Grounded in today's real board (370 ApeWisdom tickers → 129 over the floor → top 15):

- [ ] **Fix the lifecycle labels — they're broken (highest-value item).** Every one of the top-15
  board names is tagged `hot` (50 of the full scored set are `hot`, 37 `sustained`, 42 `cooling`).
  With ~4 weeks of baseline, `classify_state`'s thresholds (`velocity ≥ 1.5 AND surprise > 0.5`)
  no longer discriminate — `hot` is meaningless. Re-tune so hot / sustained / cooling actually
  separate (e.g. raise the hot bar; require real volume, not just a tiny-base spike).
- [ ] **Raise the noise floor.** `min_mentions: 5` fills the board with 5–7-mention micro-blips —
  a ticker going 1→5 mentions scores `hot` on a near-zero base (e.g. SSD: 5 mentions, 1 yesterday).
  Experiment with 8–12; measure the share of the board under 10 mentions before/after.
- [ ] **Tame tiny-base velocity.** Names with ~0 baseline get ∞ engine-velocity and huge surprise
  (FCEL: 6 mentions, surprise 4.1, ranked #2 above 50-mention names). Check the surprise-vs-volume
  balance in the composite so a 5-mention blip can't outrank a real climber.
- [ ] **Confirm theme coverage** — KEEL + the watchlist themes surface correctly on real boards.

**Exit:** lifecycle labels that discriminate on real data, a board not dominated by micro-blips,
and config values (`min_mentions`, lifecycle thresholds) documented and backed by observed output.

## Phase C — Harden against manipulation (lower priority now)

- [ ] **Sockpuppet brigades / account-age gating** — note: the per-author whale cap and distinct-
  author floor only apply to the raw-Reddit path, which isn't live. For the ApeWisdom path the bot
  inherits whatever filtering ApeWisdom does (no author signal). Revisit if/when raw Reddit returns.
- [ ] **LLM summary integrity** — structured output + an output validator that rejects markup.

## Phase D — Make it more useful (backlog)

- [ ] **Backtest the signal** — does freshness (or any fleet monitor) predict next-day price moves?
  The deepest open question; do it once Phase B has produced a signal worth trusting.
- [ ] **Per-monitor backtests** — do insider buys / congressional trades / Fed events move the
  tagged names? (The fleet creates new, cleaner things to backtest than Reddit chatter.)
- [ ] Per-ticker sparklines (wire the dashboard `trend` polyline to real 90-day history).
- [ ] Mid-day breakout flash (push when a name crosses a velocity/surprise threshold intraday).
- [ ] Crypto coverage check (24/7 markets vs the daily cadence); mobile-friendly dashboard pass.

---

## Open questions

- Does freshness have *predictive* value, or is it a popularity mirror? (Phase D backtest.)
- What are the right `min_mentions` + lifecycle thresholds on real data? (Phase B answers.)
- Keep DeepSeek for summaries, or a local model (cost + injection surface)?

## Decision log

- **2026-06-01** — Built v1.0 from the plan via subagent-driven TDD. Kept scope as a *signal
  radar* (publish/notify), explicitly **not** a trader.
- **2026-06-02** — UI sprint + the original Trump Truth Social monitor.
- **2026-06-26** — Shipped the 4-monitor fleet (PRs #1/#2) — reusable framework + EDGAR, Fed,
  Congress, all verified against live data; EDGAR confirmed firing in production CI. Discovered
  Phase B was written for the pre-ApeWisdom path and **reframed it** around what's actually live
  (`min_mentions` + lifecycle labels). The real board exposed the two concrete problems now driving
  Phase B: every board name is labeled `hot`, and a `min_mentions: 5` floor that's too low.
