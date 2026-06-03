# Still Running Lane — Design

**Date:** 2026-06-03
**Status:** Approved (pending spec review)

## Problem

The radar ranks one board by a composite score (`score.py:45`):

```
score = bounded_surprise*10 + accel_pts + volume_pts
```

`accel_pts` (24h mention growth, capped at 30) dominates during baseline burn-in and
decays fast once growth flattens. A name that genuinely broke out — e.g. MRVL on
2026-06-02 (742 mentions, `state=new`, score 44.3) — collapses the next day even though
absolute buzz *and* price are still rising (931 mentions, `state=sustained`, score 25.9):
its 24h growth fell from ~10×+ (accel maxed at 30) to 1.25× (accel ~3.8). The board is
tuned to catch the *moment* of breakout and actively sheds proven momentum names the day
after they pop — exactly where a lot of follow-through trades live.

## Goal

Keep recently-broken-out, still-alive names visible **without** diluting the early-detection
board. Preserve "get in early" as the primary board; add a separate lane for "proven
momentum still running."

## Approach (chosen)

A **separate "Still Running" lane** rendered below the main board. The main board is
unchanged (acceleration-ranked). The lane surfaces names that broke out recently and are
still elevated — and it specifically rescues them as they drop *below* the top-15 cutoff.

Rejected alternatives:
- *Blend a sustain term into the single score* — muddies the early-detection signal the
  board exists to provide.
- *Grace-period stickiness* — time-based, ignores whether the name is actually still elevated.

## Inclusion rule

A name qualifies for the Still Running lane iff ALL hold:

1. **Alive today** — today's `state` ∈ {`sustained`, `hot`}. Excludes `new` (those are early
   plays) and `cooling` (fading out).
2. **Broke out recently** — `state` was `new` or `hot` on ≥1 of the prior
   `still_running.lookback_days` days (default 3), read from `history.days_for(ticker)`,
   excluding today.
3. **Off the board** — not present in the top-`top_n` board. The lane's purpose is to hold
   names that have fallen below the acceleration cutoff, so on-board names are excluded to
   avoid duplication. (A name on the board today appears in the lane only once it drops off.)
4. Clears the noise floor — already guaranteed for any name present in `signals`.

## Ranking within the lane

```
key = min(velocity, still_running.velocity_cap) * log10(max(mentions, 10))
```

- `velocity` = `weighted_today / baseline_mean` — how elevated the name still is vs its own
  90-day norm (already computed in `_finalize`, exposed on the Signal).
- `log10(mentions)` weights by conversation size.
- `velocity_cap` (default 10) stops a thin-baseline outlier (very small `baseline_mean`,
  huge velocity) from dominating.

Sort descending; take the top `still_running.max_items` (default 5). "Most still-elevated
first," as chosen.

## Enrichment

Still Running names live outside the top-`top_n` board, so they currently lack
price / news / about / DeepSeek summary (the `run.py:42-53` loop only enriches `board`).

- Refactor that per-ticker enrichment loop into a reusable helper
  (e.g. `enrich_ticker(s, by_ticker, about_cache, about_ua, themes)`).
- Run it over `board + still_running` (de-duplicated; lane is already board-disjoint).
- Cost: ≤ `max_items` (5) extra names enriched per run — a few extra news/price/DeepSeek
  calls. Accepted (full enrichment, not a lighter price-only treatment).

## Rendering

**Dashboard.** New "Still Running" section below the main board / movers, reusing the
existing listing-card style. Per card: ticker, company name, mentions, vel× (vs yesterday),
**price + % change**, and "running N days" — where N = `run_day` minus the *most recent*
prior day with `state` ∈ {`new`, `hot`} (the qualifying breakout). Hidden entirely when the
lane is empty (never fabricate).

**Email.** Compact "Still Running" block under the main table: ticker · price · % change ·
"running N days". Short; omitted when empty.

## Config

New block in `config.yaml`:

```yaml
still_running:
  lookback_days: 3     # broke out (new/hot) within this many prior days
  max_items: 5         # lane size
  velocity_cap: 10     # cap on the elevation multiplier when ranking
```

Loaded via `radar/config.py` with the defaults above when the block is absent (back-compat
with existing config + tests).

## Code shape

- **`radar/still_running.py`** (new) — pure function
  `still_running(signals, history, run_day, board, cfg) -> list[Signal]`. Keeps `score.py`
  focused. Unit-testable in isolation.
- **`radar/run.py`** — compute the lane after `board`, enrich lane names via the shared
  helper, thread into `_build_context` (new `still_running=` context key) and the email row
  builder.
- **`radar/render.py` + templates** — render the dashboard section.
- **`radar/email_report.py`** — render the email block.
- **`radar/config.py`** — parse the `still_running` block with defaults.

## Testing

Unit tests for `still_running.py` against synthetic `History`:

- Qualifies: broke out (new/hot) within lookback, `sustained`/`hot` today, off the board.
- Excluded — `new` today (it's an early play).
- Excluded — `cooling` today.
- Excluded — last breakout older than `lookback_days`.
- Excluded — currently on the top-`top_n` board.
- Ranking — higher `velocity × log10(mentions)` sorts first; `velocity_cap` bounds a
  thin-baseline outlier.
- Lane truncated to `max_items`.
- Empty lane when nothing qualifies (renders nothing, sends nothing).

The existing scoring invariants (INV-1..INV-8) and the main board are untouched.

## Out of scope

- No change to the main board scoring or ordering.
- No new historical backfill — the lane uses `state` already recorded per day.
- No "cooling" / exit lane (separate idea).
