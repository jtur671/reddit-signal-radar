---
project: Reddit Signal Radar
feature: Phase B — Trust the signal (lifecycle labels + noise floor)
status: design — approved, pre-implementation
created: 2026-06-26
tags: [spec, reddit-signal-radar, phase-b, scoring]
---

# Phase B — Lifecycle Labels + Noise Floor

## Summary

Two grounded changes to make the live (ApeWisdom) board's signal trustworthy:

1. **Raise the noise floor** — `min_mentions: 5 → 10` in `config.yaml`.
2. **Make the lifecycle labels discriminate** — replace the absolute-threshold
   `classify_state` with a **relative tiering pass**: rank the displayed board by `surprise`
   (z-score vs the 90-day baseline) and split into even thirds — `new` (no baseline) /
   `hot` (top third) / `sustained` (middle) / `cooling` (bottom third).

Both are scoped to the **live ApeWisdom path** (`score_aggregates`). The raw-Reddit path
(`score_signals`) and its `classify_state` are left untouched (not live; not worth churning).

## Why (grounded in the real board, 2026-06-26)

Generated the live board and measured it:

- **Lifecycle labels are meaningless.** All 15 board names are tagged `hot` (full scored set:
  50 hot / 37 sustained / 42 cooling). `classify_state` keys "hot" off **engine velocity**
  (`weighted ÷ baseline`), which is effectively ∞ for any low-baseline name, so a 1→5-mention
  blip looks as hot as a real breakout. With ~4 weeks of baseline the absolute thresholds
  (`velocity ≥ 1.5 AND surprise > 0.5`) no longer separate anything.
- **Noise floor too low.** `min_mentions: 5` keeps 129 of 370 tickers; the board fills with
  5–7-mention micro-blips (e.g. SSD: 5 mentions, 1 yesterday → "hot"). With `min_mentions: 10`
  the tracked set drops to ~70 and every board name has ≥10 mentions — the blips are gone.
- **Tiering across the full set does NOT fix the board (verified).** Surprise terciles over all
  ~70 tracked names split evenly (24/23/23), but the board — selected by *composite score*,
  which is dominated by surprise — is still 15/15 `hot` (the top-composite names are the
  top-surprise names). The fix must tier **within the board**: ranking the 15 displayed names
  by surprise into even thirds yields ~5 hot / 5 sustained / 5 cooling.

## Decision: relative tiering by surprise, within the board

The user chose **four even tiers** (labels as a relative momentum ranking, not an absolute
"breaking" flag) ranked by **surprise**. Accepted tradeoff: with board-relative tiers,
`cooling` means *"lowest-momentum third of today's board,"* not literally declining — a still-
positive name (e.g. surprise 0.87) can read `cooling`. This is inherent to relative labeling
and is on the record.

## Changes

### 1. `config.yaml`
```yaml
noise_floor:
  min_mentions: 10      # was 5 — removes 5–7-mention micro-blips from the live board
```
(The `min_distinct_authors` / `max_author_weight` keys stay — they only affect the raw-Reddit
`score_signals` path, which is not live.)

### 2. `radar/score.py` — `assign_relative_states(signals, board)`
```python
def assign_relative_states(signals, board):
    """Relative lifecycle tiers: rank the displayed board by surprise and split into even
    thirds so the labels discriminate instead of collapsing to all-'hot'. No-baseline names
    stay 'new'. Thresholds come from the board (what the user sees); off-board names fall
    below them -> 'cooling' as they fade."""
    surps = sorted(s.surprise for s in board if s.baseline_mean > 1e-9)
    if not surps:
        return
    t1, t2 = surps[len(surps) // 3], surps[(2 * len(surps)) // 3]
    for s in signals:
        if s.baseline_mean <= 1e-9:
            s.state = "new"
        elif s.surprise >= t2:
            s.state = "hot"
        elif s.surprise < t1:
            s.state = "cooling"
        else:
            s.state = "sustained"
```

### 3. `radar/run.py` — call it once, after board selection
Right after `board = top_signals(signals, cfg.top_n)` (and `still = still_running(...)`), call
`assign_relative_states(signals, board)` so the board, the Still-Running lane, Today's Read,
and `history.record(...)` all use the relative label.

## Architecture notes

- `_finalize` still sets a provisional `s.state` via `classify_state` (unchanged) — used by the
  raw-Reddit path and as a fallback; the new pass overrides it for the live flow.
- `assign_relative_states` is a pure mutation over a list of `Signal`s given a reference board —
  one clear responsibility, trivially testable in isolation (no I/O).
- The dashboard already colors tiles/cards by state (green=hot, cyan=cooling) and `run.py`'s
  `_emoji`/`_css` map state → style for hot/sustained/cooling/new — no render change needed; the
  board simply stops being all-green.

## Scope boundary (explicitly NOT in this change)

- `classify_state` and the raw-Reddit `score_signals` path — untouched.
- The composite *score* / ranking — untouched (the noise-floor raise already removes the
  micro-blips that were ranking high; re-balancing surprise-vs-volume is deferred).
- `min_distinct_authors`, `max_author_weight`, stoplist gardening — N/A on the live path.
- Phase C (manipulation hardening) and Phase D (backtest) — separate.

## Testing

- **New** `tests/test_score.py::` cases for `assign_relative_states`:
  - even split: a 15-name board with spread surprises → ~5 hot / 5 sustained / 5 cooling.
  - `new` preserved: a no-baseline signal stays `new` regardless of surprise.
  - off-board: a signal with surprise below the board's bottom tercile → `cooling`.
  - empty/degenerate board (no baseline-having names) → no crash, states unchanged.
- **Updated** existing lifecycle assertions: the `classify_state` tests in `test_score.py` stay
  (raw path unchanged), but any test asserting the *live* board's per-name state, and any
  `test_invariants.py` check that pins absolute state values, are updated to the relative model.
  The plan enumerates exactly which.
- **Regression:** the full suite stays green; `min_mentions: 10` must not break fixture-based
  scoring tests (adjust fixtures/expectations where a fixture relied on the 5 floor).

## Risks / open items

- **Relative `cooling` semantics** — accepted (see Decision). If it reads wrong in practice, a
  later refinement could floor `cooling` to genuinely-declining names (surprise < 0 or
  vel_24h < ~0.9) and split only the rest — deferred.
- **`min_mentions: 10` is a starting value** — tune from a few days of boards (same burn-in
  discipline); easy config flip.
- **Board-derived thresholds applied to off-board names** push most of the long tail to
  `cooling`; fine for display (those names are fading) and for `history` (records the label).

## Decision log

- **2026-06-26** — Chose relative tiering by surprise **within the board** over absolute
  thresholds (brittle, caused all-`hot`) and over full-set terciles (verified: leaves the board
  all-`hot`). Raised `min_mentions` 5 → 10. Kept `classify_state` for the non-live raw path.
