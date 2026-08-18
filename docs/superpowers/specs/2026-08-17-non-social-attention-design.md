---
project: Reddit Signal Radar
phase: E2 — Non-social attention
spec: design
date: 2026-08-17
status: draft (awaiting owner review)
research: [[2026-08-17-community-mining]]
depends: [[2026-08-17-ticker-article-mapping-design]]
---

# E2 — Non-social attention

Two keyless sources that see attention the board cannot: Wikimedia pageviews (does the
wider world care?) and short interest (how much squeeze fuel is loaded?).

**They are not peers, and the roadmap's framing of them as one slot is the design error
this spec corrects.** Pageviews are same-day fresh and become a published component.
Short interest is 11–24 days stale and twice-monthly; it is a context field and must
never enter a daily composite.

## 1. Why

The board measures Reddit. Every Phase-2 source added since — Tradestie, FINRA short
*volume*, CBOE, Cramer — measures markets or filings. Nothing measures whether anyone
*outside* the forums is paying attention, which is exactly the discriminator between a
genuine story and a brigade.

### 1.1 The freshness measurement that splits the phase in two

| | Wikimedia pageviews | Short interest |
|---|---|---|
| Cadence | daily | **twice monthly** (~15th, month-end) |
| Data available for | D-1 | latest settlement |
| Lands at | ~02:30 UTC on D+1 (measured 13/13 days, range 02:14–02:49) | settlement + **9–12 days** |
| Board publishes | 10:17 UTC | — |
| Margin / staleness | **+7.5 h** | **11–24 days**, sawtoothing |

Measured 2026-08-17: latest available settlement is **2026-07-31 (17 days stale)**;
the 2026-08-14 settlement returns empty and publishes 2026-08-25. FINRA's published
schedule corroborates both probes exactly.

**Consequence:** a fortnightly step function inside a daily-varying composite would be
misattributed by the backtest to whichever day the step landed on. Short interest is
therefore excluded from the composite by design, not by caution.

## 2. Design — Tier 1: Wikimedia pageviews

### 2.1 Endpoint and one-request history

```
https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/
  en.wikipedia/all-access/user/{ARTICLE}/daily/{YYYYMMDD}/{YYYYMMDD}
```

A date range returns in **one request**: measured 2026-08-17, `Tesla,_Inc.` over
20260714–20260816 returned **34 datapoints in 0.22 s**, HTTP 200. So the trailing
baseline and the current value arrive together and **no warm-up period is required** —
the component is live on the first run.

Two non-obvious requirements, both measured:

- **A non-empty User-Agent is mandatory.** Empty UA → HTTP 403 with a robot-policy
  notice. The existing `"reddit-signal-radar/0.1 (open-source ticker signal bot)"`
  string satisfies it.
- **Use `agent=user`, not `all-agents`.** Measured on `Nvidia`, 2026-08-16: user 3,765 /
  spider 546 / automated 1,190 / all-agents 5,501. `all-agents` carries **32% bot
  inflation**, and bot traffic is not attention.

`{ARTICLE}` is the exact title from [[2026-08-17-ticker-article-mapping-design]].
**A ticker with no mapping gets no request and no series** — never a guessed title.

### 2.2 Scoring: self-relative spike, not cross-sectional rank

The signal being measured is *"is this name unusually looked up right now"*, which is a
question about a ticker against its own history. A board-relative percentile would
mostly rank market cap — NVDA would outrank a genuinely spiking micro-cap every day.

Fetch the 35 days ending D-1. Then:

- `current` = views on D-1
- `baseline` = **median** of the 28 days ending D-2 (median, not mean — a single prior
  spike must not suppress today's)
- `ratio = current / baseline`
- `attention = 50 + 25 * clamp(log2(ratio), -2, +2)`

So ratio 1.0 → 50, 4× → 100, ¼× → 0, and the response is symmetric in log space. Worked
example from the live probe (2026-08-17): TSLA current 2,554 against a 2,816.5 median →
ratio 0.9068 → log2 −0.1411 → `attention` **46.47**. Correctly unremarkable. Anchors
verified: 1.0→50.0, 2.0→75.0, 4.0→100.0, 0.25→0.0, and 8.0/0.1 clamp to 100.0/0.0.

**Emit `None`, not a score, when:**

- the ticker has no article mapping, or
- fewer than 21 of the 28 baseline days returned data, or
- `baseline < 10` views/day.

That last floor matters: on a near-zero baseline the ratio explodes and a jump from 2
views to 12 would score 100. A micro-cap with no meaningful Wikipedia traffic has no
attention signal, and `None` is the honest encoding — `composite.py`'s renormalization
already handles it.

### 2.3 Published, not weighted

`attention` is added to `components_for`'s dict in `radar/composite.py` and
**deliberately given no entry in `config.yaml`'s `composite.weights`**.

`composite.py:54` filters on `weights.get(k, 0) > 0`, so the key is published in
`data.json`'s `components` block and excluded from the blend. This costs **no new blend
code**, requires **no rebalance** of the existing seven weights (which
`tests/test_run_smoke.py:51` pins to sum 1.0), and — because the composite value is
bit-for-bit unchanged — **is not a regime boundary**. The backtest series stays
comparable across this phase.

**Why unweighted rather than weighted at a guessed value.** Two independent reasons:

1. The power gate needs 150 days and has 76 (≈2026-11-01), so no measured weight is
   available yet.
2. More importantly, the recalibration story the roadmap assumes **does not exist**.
   `radar/backtest.py`'s `_frames()` emits the raw velocity engine score, not composite
   components; a grep for `components`/`short_ratio`/`cramer` in that module returns
   only the `REGIME_NOTES` strings. **Per-component ICs are computed nowhere in this
   repo.** Weighting now would encode a guess and re-price all seven live components to
   do it.

This is the first deliberate use of the unweighted path, so §4 pins the behavior with a
test rather than leaving it as an emergent property of a filter expression.

**↪ follow-up, not this phase:** building the per-component IC estimator in
`backtest.py` is the prerequisite for ever weighting `attention`. The raw inputs are
already persisted — `history.annotate` writes `ts_bull`, `short_ratio`, `pc_ratio`,
`uoa`, `cramer` per ticker-day — so this is an estimator, not an ingest. It should also
correct the "a config change, not a code change" claim, which currently appears in
`radar/composite.py:5`, `config.yaml:111` and `README.md:66` and is false as written.

### 2.4 Cost and failure

~15–20 requests per run (board plus Still Running), 0.22 s each, with the house courtesy
sleep between them. Fail-soft per `radar/cramer.py`'s contract: a failed fetch yields
`None` for that ticker, not a run failure. `health.json` gains a `wikimedia` source
entry (`ok`/`down`) plus a footer LED, per the house rule that every source reports
itself. `history.annotate` records `pageviews` and `attention` per ticker-day so the
backtest can use them once the IC estimator exists.

## 3. Design — Tier 2: short interest as context

### 3.1 FINRA, not Nasdaq

```
POST https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest
Accept: application/json
```

Despite the `otcMarket` path it covers listed names — measured `marketClassCode` values
include NNM, NYSE and ARCA. **22,341 symbols** for settlement 2026-07-31.

Nasdaq's endpoint is the same data — MVIS @ 2026-07-15 returns `59527128 / 6.73` from
both, identically — but it is one-ticker-per-request, returns comma-formatted strings,
**blocked a default curl UA with HTTP 000**, and is widely IP-blocked from cloud egress.
FINRA is keyless, batchable and has no bot posture. Use FINRA.

`daysToCoverQuantity` ships **directly**; no average-daily-volume computation is needed,
and `averageDailyVolumeQuantity` arrives alongside it.

### 3.2 Vendoring, and the sentinel trap

Twice-monthly data is the ideal vendoring case. Snapshot
`data/short_interest.json` on the orphan `data` branch, refreshed only when a **new
settlement date appears**; served from snapshot otherwise. Respect the hard **5,000-row
cap** — a full pull is 5 paginated calls. Vendor the whole universe (trimmed to
`symbolCode`, `currentShortPositionQuantity`, `daysToCoverQuantity`, `settlementDate`)
so a name entering the board later is already covered and board churn never triggers a
live fetch.

**Filter `daysToCoverQuantity == 999.99`.** It is a sentinel for zero/near-zero average
volume (measured: `AAALF`, ADV 0 → DTC 999.99), not a real 999-day cover. Unfiltered it
dominates any sort or ranking.

### 3.3 `as_of` is not optional

`days_to_cover` and `short_interest_shares` ship in each `signals` row **with the
settlement date beside them**, and every surface that renders the number renders the
date. At 11–24 days stale on a board that publishes daily, a bare number implies a
freshness it does not have — and the field sits next to `short_ratio`, a genuinely D-1
value, which makes the confusion easy and consequential.

This field is **not** added to `components_for`. It is not a composite component in any
form, weighted or otherwise.

## 4. Testing

House style: `monkeypatch.setattr` on each module's private fetch helper, fixtures under
`tests/fixtures/`. The suite is hermetic as of `b6b90ad` and stays that way — **no live
calls, and `tests/conftest.py`'s autouse guard must be extended to cover both new
fetchers.**

1. Spike math, table-driven: ratio 1.0→50, 4.0→100, 0.25→0, 2.0→75; clamped beyond ±2 in
   log space.
2. Median, not mean — a single 10× day in the baseline window must not suppress today's
   score.
3. `None` on each of the three conditions in §2.2 separately: no mapping, <21 baseline
   days, baseline <10 views.
4. **Unmapped ticker makes no HTTP request** — asserted as a call count of zero, not
   just a `None` return. This is the E2a anti-fuzzy guarantee holding at the E2 boundary.
5. **`attention` appears in `components` and does NOT change the composite value.**
   Assert the blended number is identical with and without the key present. This pins
   §2.3's central claim, which otherwise rests on an easily-broken filter expression.
6. The published `weights` block still sums to 1.0 and still has exactly seven keys.
7. `999.99` days-to-cover is filtered out.
8. Short-interest snapshot is refreshed only when the settlement date advances.
9. `as_of` is present wherever `days_to_cover` is rendered.
10. Both sources fail soft: upstream down ⇒ `None`/snapshot + `degrade.warn` + a `down`
    LED, never a run failure.

## 5. Risks

| Risk | Mitigation |
|---|---|
| Wikimedia's D-1 load time drifts past 10:17 UTC | 7.5 h margin measured over 13/13 days. Also: the 02:14–02:49 window is the **dumps pipeline**, taken as a proxy for the AQS API's own load. **Confirm with one fetch of D-1 at board time** — this is the one open measurement in the spec |
| Article renamed upstream ⇒ series breaks | Wikipedia redirects resolve; a hard 404 yields `None` and a `down` LED, not a wrong series |
| Spike ratio is noisy on thin traffic | The `baseline < 10` floor plus the 21-of-28 coverage requirement |
| `attention` silently starts affecting the composite | Test 5 asserts the composite is unchanged; test 6 pins the weight block at seven keys |
| Short interest read as fresh | `as_of` mandatory on every surface (§3.3); excluded from the composite entirely |
| FINRA changes the `otcMarket` path | Vendored snapshot means an outage costs nothing for up to two weeks |

## 6. Out of scope

- **Weighting `attention`.** Blocked on the IC estimator (§2.3), which is itself blocked
  on the 150-day power gate (76 days as of 2026-08-17).
- **The per-component IC estimator** — named as the follow-up in §2.3, specced
  separately.
- Short interest as a composite component, in any weighted or gated form.
- Non-US listings, ETFs and crypto symbols — structurally unmappable per E2a.
- Reddit RSS as a raw-text path: **dead from CI** (E0 measured 429 with
  `x-ratelimit-remaining: 0.0` on the first request; the Actions IP range shares one
  exhausted bucket). Only a self-hosted runner could revive it.
