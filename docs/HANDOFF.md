---
project: Reddit Signal Radar
doc: handoff / live state
phase: E — Deepen the signal
updated: 2026-08-17
owner: jason
tags: [handoff, reddit-signal-radar]
---

# HANDOFF — Phase E live state

> **[[ROADMAP]] is the shape. This doc is the state.** Roadmap changes when the plan
> changes; this changes every time something lands. If the two disagree, this one is
> right — then fix the roadmap.

**Read this first if you are picking the project up cold.** Everything below marked
`measured` was verified against the live source on the date shown. Everything marked
`assumed` was not — do not build on it without measuring. That distinction is the point
of this document.

---

## 1. Where things stand right now

| | |
|---|---|
| Branch | `harden/audit-fixes` (ahead of `main`; security-audit fixes + this research) |
| Prod | daily board + email 6:17 AM ET; 5-monitor fleet on a 30-min tick |
| Tests | **327 passed in 48.9s** (measured 2026-08-17, `.venv`). Re-run rather than quote: `source .venv/bin/activate && python -m pytest` |
| Data branch | `origin/data` — 654 tickers, 76 daily snapshots, 8,364 ticker-days (measured 2026-08-17) |
| Backtest power gate | needs 150 days, has 76 → opens ≈ **2026-11-01** |
| Current phase | **E1 — Catalyst layer**, spec not yet written |

### Open defect found during research (blocks E1)

`radar/composite.py:43` — `"events": 100.0 if s.ticker in alert_tickers else 0.0`, and
`radar/run.py:154` builds `alert_tickers` as a flat set across all monitors, discarding
which monitor fired. Every other component is oriented higher-is-more-bullish. So the
catalyst layer would score a 424B5 dilution and a 25-NSE delisting as **+100** — the
radar would rank a diluting company *higher* for diluting. Sign this before E1 ships.

### Known, accepted, not a bug

Board breadth halved on **2026-08-08**: min raw mentions 5→10, names/day ~119→~54. That
is the Phase B `noise_floor.min_mentions` raise landing as designed. It does thin the
backtest's cross-sections, and it means the 2026-08-07/08 boundary marks **two**
simultaneous regime changes (composite merge + noise floor) — keep them distinct in
`regime_notes`.

---

## 2. Checklist — tick as it lands

Each item carries its **update hook**: the exact thing to do to this doc when it's done.
An item is not done until its hook has been run.

### E0 — Settle the cloud-IP question · blocks E3

- [ ] Run the probe
      ```bash
      git push -u origin harden/audit-fixes
      gh workflow run probe-sources.yml --ref harden/audit-fixes
      sleep 90 && gh run view --log
      ```
      **↪ hook:** paste the `HTTP=` line for every endpoint into §3 below, set each
      row's verdict, and stamp the date. Then unblock or kill E3 accordingly.
- [ ] Delete `.github/workflows/probe-sources.yml`
      **↪ hook:** tick this, and note in §5 that the probe is gone so nobody hunts for it.

### E1 — Catalyst layer · next

- [ ] Sign the `events` composite component
      **↪ hook:** strike the "Open defect" block in §1 and move it to §5 with the commit SHA.
- [ ] Write the spec → `docs/superpowers/specs/YYYY-MM-DD-catalyst-layer-design.md`
      **↪ hook:** link it here and in [[ROADMAP]]'s E1 block.
- [ ] Form-parameterized EDGAR monitor (`forms=` and `q=` from config)
- [ ] Wire the four classes (`dilution` / `shelf` / `activist` / `delisting`)
- [ ] Widen the watch gate to the full 90-day history
- [ ] **Measure real alert volume after 1 week live** and compare to the ~3.2/day estimate
      **↪ hook:** put the measured number in §4 next to the estimate. If it is 2× off,
      say so — a wrong estimate that goes uncorrected is how the next plan gets built wrong.
      **↪ hook:** add a `regime_notes` entry — a new alert class changes the `events`
      component, which changes every composite, which is a backtest regime boundary.
- [ ] Update [[ROADMAP]] decision log
      **↪ hook:** tick E1 in [[ROADMAP]], move this whole block to §5, set §1 phase to E2.

### E2 — Non-social attention

- [ ] Decide: new weighted components, or published-but-unweighted until the power gate
      **↪ hook:** record the decision and its reason in §5 — this one will be re-litigated.
- [ ] Wikimedia pageviews ingest
- [ ] Short interest + days-to-cover ingest
      **↪ hook:** if these become composite components, add a `regime_notes` entry and
      update `config.yaml`'s `composite.weights` comment.

### E3 — Second attention source · blocked on E0

- [ ] StockTwits ingest (board source + direction + `watchlist_count`)
      **↪ hook:** add `stocktwits` to `health.json`'s `sources` block and to the README's
      source list; add a footer LED. Every source the radar has does this — match it.

### E4 — Agent layer

- [ ] Spec the analyst/debate layer
      **↪ hook:** this one changes what the *product* is, not just the data. Re-read
      the "radar, not a trader" scope decision (2026-08-07 decision log) before writing it.

---

## 3. Endpoint status board

Everything here was measured from a **residential IP on 2026-08-17** unless stated.
Residential ≠ CI: the original raw-Reddit path died on exactly that gap.

| Endpoint | Residential | From CI | Verdict |
|---|---|---|---|
| ApeWisdom | 200 | **200 (prod, daily)** | in prod — the baseline everything else is judged against |
| Tradestie | 200 | **200 (prod, daily)** | in prod |
| EDGAR FTS `efts.sec.gov` | 200 | **200 (prod, fleet)** | in prod — accepts any `forms=` code |
| SEC `data.sec.gov` submissions | 200 | 200 (prod) | in prod |
| FINRA Reg SHO | — | 200 (prod) | in prod |
| CBOE chains | — | 200 (prod) | in prod |
| **StockTwits** stream + trending | **200**, CF-fronted like ApeWisdom | ❓ **probe** | E3 gate |
| **reddit.com `/*.rss`** | **200**, 1 req/60s per IP | ❓ **probe** | E-later |
| reddit.com `/*.json` | — | **403 (known)** | dead, do not retry |
| Wikimedia pageviews | 200 | ❓ probe | E2 |
| Nasdaq short-interest | 200 | ❓ probe | E2 |
| FINRA consolidated short interest | 200 (CSV, keyless) | ❓ probe | E2 |
| SEC FTD zip | 200 **only with a contact UA** (403 without) | ❓ probe | context only |
| Polymarket Gamma / Kalshi | 200 / 200 | — | recorded, not recommended — ticker mapping unsolved |
| Bluesky `public.api.bsky.app` | **403** (needs free auth) | — | deferred |
| 4chan `/biz/` | 200 | — | **skip** — GME/BBBY/crypto zombies |
| Hacker News (Algolia) | 200 | — | **skip** as a ticker source |

---

## 4. Numbers to check against reality later

Every one of these is an estimate that a future session will be tempted to quote as
fact. Replace with a measurement when you can.

| Claim | Value | Basis | Replace when |
|---|---|---|---|
| Catalyst alerts/day, 90-day gate | ~3.2 unique tickers | EDGAR FTS ∩ history, 2026-08-10→14 | 1 week after E1 goes live |
| Catalyst alerts/day, 7-day gate | ~1.2 | same | — (not chosen) |
| Backtest power gate opens | ≈2026-11-01 | 76/150 days at 1/day | every backtest run |
| Board names/day (post-floor) | ~54 | history, 2026-08-08→17 | monthly |
| Reddit RSS budget | 1 req / ~60s / IP | `x-ratelimit-*` headers | if RSS is ever used |
| EFTS page cap | 100 hits | `len(hits)` vs `total` | if paging is added |
| Test suite | 327 passed / 48.9s | measured 2026-08-17 | every branch |

---

## 5. Landed (newest first)

Move completed checklist blocks here with the date and commit SHA. Keep it short — the
decision log in [[ROADMAP]] is where *why* lives; this is just *what*, so a future
session can tell "not done yet" from "done and reverted".

- **2026-08-17** — Community-mining research pass; [[2026-08-17-community-mining]],
  Phase E added to [[ROADMAP]], this doc created. Probe workflow written (not yet run).
- **2026-08-17** — Security-audit fixes (`f5fae9e`): URL scheme allowlist, CI secret
  blast radius, SHA-pinned actions.

---

## 6. House rules a new session will otherwise violate

- **Bot state lives on the orphan `data` branch, not `main`.** Local `data/` is stale.
  `git fetch origin data && git checkout origin/data -- data/` before reasoning about
  real state. Committing state to `main` is a regression.
- **Every source fails soft and reports itself** in `health.json`'s `sources` block
  (`ok`/`down`/`fallback`/`unused`) plus a footer LED. A new source that can take the
  run down, or that fails silently, is not finished.
- **Third-party GitHub JSON feeds get vendored** to the data branch with a dated
  snapshot (see `cramer_snapshot.json`) so the signal survives upstream deletion.
  Both feeds already in prod (`cramer`, `congress`) follow this.
- **GitHub Actions are pinned to commit SHAs, not tags** — those runners hold every
  repo secret.
- **Anything that changes a composite component is a backtest regime boundary.** Add a
  dated `regime_notes` entry, or the backtest silently compares incomparable periods.
- **Never quote a test count, ticker count, or date you did not run a command for.**
  This project's docs have been wrong that way before; the tables above exist so the
  next session measures instead of remembering.
