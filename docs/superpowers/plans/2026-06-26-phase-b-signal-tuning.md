# Phase B — Lifecycle Labels + Noise Floor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the live board's lifecycle labels discriminate (relative tiers by surprise instead of all-`hot`) and raise the noise floor so micro-blips drop off.

**Architecture:** Two changes on the live ApeWisdom path. (1) `config.yaml` `min_mentions: 5 → 10`. (2) A new pure function `radar/score.py:assign_relative_states(signals, board)` that ranks the displayed board by `surprise` into even thirds and overrides each signal's `state`; called once in `run.py` after board selection. `classify_state` and the raw-Reddit `score_signals` path are left untouched.

**Tech Stack:** Python 3.11, pytest. No new dependencies.

## Global Constraints

- Python floor **3.11**; `from __future__ import annotations` already in `score.py`.
- No new pip dependencies.
- **Live path only:** changes apply to the ApeWisdom `score_aggregates` flow via `run.py`. Do NOT modify `classify_state` or `score_signals` (raw-Reddit path, not live, still tested).
- `assign_relative_states` is a **pure mutation** over a list of `Signal`s given a reference board — no I/O, no network.
- Tier rule (verbatim): thresholds from the board's `surprise` distribution; `t1 = surps[len//3]`, `t2 = surps[2*len//3]`; `new` if `baseline_mean <= 1e-9`, else `hot` if `surprise >= t2`, `cooling` if `surprise < t1`, else `sustained`.
- Each monitor/scoring change keeps the full suite green.

---

## File Structure

**Modify:**
- `config.yaml` — `noise_floor.min_mentions` 5 → 10
- `tests/test_config.py:4` — assertion 5 → 10
- `radar/score.py` — add `assign_relative_states(signals, board)`
- `tests/test_score.py` — add unit tests for `assign_relative_states`
- `radar/run.py` — import + call `assign_relative_states(signals, board)` after board selection

No new files.

---

## Task 1: Raise the noise floor

**Files:**
- Modify: `config.yaml` (the `noise_floor` block)
- Test: `tests/test_config.py:4`

**Interfaces:**
- Consumes: nothing.
- Produces: `config.yaml` `noise_floor.min_mentions == 10` (read by `score_aggregates` on the live path and by `test_config.py`).

- [ ] **Step 1: Update the failing assertion first (TDD: it will fail until config changes)**

In `tests/test_config.py`, change line 4 from:
```python
    assert c.half_life_hours == 24 and c.noise_floor.min_mentions == 5
```
to:
```python
    assert c.half_life_hours == 24 and c.noise_floor.min_mentions == 10
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_config.py::test_load_config -q`
Expected: FAIL — config still says 5, assertion wants 10.

- [ ] **Step 3: Raise the floor in config.yaml**

In `config.yaml`, in the `noise_floor:` block, change:
```yaml
  min_mentions: 5
```
to:
```yaml
  min_mentions: 10   # raised from 5 (Phase B): drops 5-9-mention micro-blips off the live board
```
(Leave `min_distinct_authors` and `max_author_weight` unchanged — they only affect the non-live raw-Reddit path.)

- [ ] **Step 4: Run the config test + full suite**

Run: `python3 -m pytest tests/test_config.py -q`
Expected: PASS.
Run: `python3 -m pytest -p no:warnings -q`
Expected: PASS — no other test reads the real `config.yaml` noise floor (the score tests use a local `min_mentions: 3` cfg; the smoke test's IREN=120/KEEL=80 both clear 10).

- [ ] **Step 5: Commit**

```bash
git add config.yaml tests/test_config.py
git commit -m "feat(score): raise noise floor min_mentions 5 -> 10 (Phase B)"
```

---

## Task 2: `assign_relative_states` — relative lifecycle tiers

**Files:**
- Modify: `radar/score.py` (add the function)
- Test: `tests/test_score.py` (append unit tests)

**Interfaces:**
- Consumes: `radar.models.Signal` (dataclass; fields `surprise: float`, `baseline_mean: float`, `state: str`).
- Produces: `assign_relative_states(signals, board) -> None` — mutates `s.state` for every `s` in `signals`, using tercile thresholds computed from `board`'s `surprise` values (baseline-having only). Returns nothing; early-returns (no change) when the board has no baseline-having names.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_score.py`:
```python
def test_assign_relative_states_even_thirds():
    from radar.score import assign_relative_states
    from radar.models import Signal
    board = [Signal(ticker=f"T{i}", surprise=float(i), baseline_mean=5.0) for i in range(1, 10)]
    assign_relative_states(board, board)            # surprises 1..9 -> t1=4, t2=7
    st = {s.ticker: s.state for s in board}
    assert [st[f"T{i}"] for i in (1, 2, 3)] == ["cooling"] * 3
    assert [st[f"T{i}"] for i in (4, 5, 6)] == ["sustained"] * 3
    assert [st[f"T{i}"] for i in (7, 8, 9)] == ["hot"] * 3


def test_assign_relative_states_preserves_new_for_no_baseline():
    from radar.score import assign_relative_states
    from radar.models import Signal
    board = [Signal(ticker=f"T{i}", surprise=float(i), baseline_mean=5.0) for i in range(1, 10)]
    newbie = Signal(ticker="NEW", surprise=9.9, baseline_mean=0.0)   # no baseline
    assign_relative_states([newbie, *board], board)
    assert newbie.state == "new"                    # high surprise but no baseline -> still 'new'


def test_assign_relative_states_offboard_below_floor_is_cooling():
    from radar.score import assign_relative_states
    from radar.models import Signal
    board = [Signal(ticker=f"T{i}", surprise=float(i), baseline_mean=5.0) for i in range(1, 10)]
    offboard = Signal(ticker="OFF", surprise=0.5, baseline_mean=5.0)  # below board's t1=4
    assign_relative_states([offboard, *board], board)
    assert offboard.state == "cooling"


def test_assign_relative_states_degenerate_board_no_crash():
    from radar.score import assign_relative_states
    from radar.models import Signal
    s = Signal(ticker="X", surprise=2.0, baseline_mean=5.0, state="sustained")
    board_all_new = [Signal(ticker="N", surprise=1.0, baseline_mean=0.0)]  # no baseline -> no thresholds
    assign_relative_states([s], board_all_new)
    assert s.state == "sustained"                   # early return -> state unchanged
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_score.py -k assign_relative_states -q`
Expected: FAIL — `ImportError: cannot import name 'assign_relative_states'`.

- [ ] **Step 3: Implement the function**

Add to `radar/score.py` (place it right after `classify_state`, near the top so it reads alongside the other labeling logic):
```python
def assign_relative_states(signals, board):
    """Relative lifecycle tiers: rank the displayed board by surprise and split into even
    thirds so the labels discriminate instead of collapsing to all-'hot'. No-baseline names
    stay 'new'. Thresholds come from the board (what the user sees); off-board names fall
    below them -> 'cooling' as they fade. Pure mutation; no I/O."""
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

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_score.py -k assign_relative_states -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add radar/score.py tests/test_score.py
git commit -m "feat(score): assign_relative_states — relative lifecycle tiers by surprise"
```

---

## Task 3: Wire the relative pass into the run

**Files:**
- Modify: `radar/run.py` (import on line 11; call after board selection ~line 50)
- Test: `tests/test_run_smoke.py` (existing — must still pass)

**Interfaces:**
- Consumes: `radar.score.assign_relative_states(signals, board)` (Task 2), the existing `signals` (full scored list) and `board` (top-N) locals in `run.main`.
- Produces: the live board + Still-Running + Today's Read + `history.record` all use the relative label.

- [ ] **Step 1: Add the import**

In `radar/run.py`, change line 11 from:
```python
from radar.score import score_aggregates, top_signals
```
to:
```python
from radar.score import score_aggregates, top_signals, assign_relative_states
```

- [ ] **Step 2: Call it after board selection**

In `radar/run.py:main`, the current lines are:
```python
    aggregates = fetch_mentions(cfg)                    # ApeWisdom; never raises
    signals = score_aggregates(aggregates, history, cfg, run_day)
    board = top_signals(signals, cfg.top_n)
    still = still_running(signals, history, run_day, board, cfg)
```
Add one line immediately after the `still = ...` line:
```python
    assign_relative_states(signals, board)              # relative lifecycle tiers (Phase B)
```
(Placed before the theme-tagging loop and `history.record`, so every downstream consumer sees the relative label.)

- [ ] **Step 3: Run the smoke test**

Run: `python3 -m pytest tests/test_run_smoke.py -q`
Expected: PASS — `run.main(["--dry-run", ...])` returns 0 and the dashboard contains IREN and KEEL. `assign_relative_states` runs over the 2-name board without error (whatever baselines IREN/KEEL have in the real `history.json`; a degenerate all-new board early-returns).

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest -p no:warnings -q`
Expected: PASS (all tests). The pre-existing `test_score.py` / `test_invariants.py` / `test_bounty.py` state assertions are unaffected — they call `score_signals` / `score_aggregates` directly (which still set `state` via the unchanged `classify_state`); only `run.main` applies the relative override.

- [ ] **Step 5: Commit**

```bash
git add radar/run.py
git commit -m "feat(run): apply relative lifecycle tiers after board selection (Phase B)"
```

---

## Self-Review

**1. Spec coverage**

| Spec requirement | Task |
|---|---|
| `min_mentions: 5 → 10` | Task 1 |
| `assign_relative_states` with the exact tier rule (new/hot/sustained/cooling) | Task 2 |
| `new` for no-baseline preserved | Task 2 (test + impl) |
| off-board names → cooling | Task 2 (test) |
| degenerate board → no crash | Task 2 (test) |
| called once after board selection, over all signals | Task 3 |
| `classify_state` / raw path untouched | Tasks 2 & 3 (not modified) |
| composite ranking untouched | (not modified) |
| update `test_config.py` for the floor | Task 1 |
| existing state assertions stay green | Task 3 Step 4 (direct-path tests unaffected) |

No gaps. **Deviation from spec, noted:** the spec's test-impact section said the `test_score.py` / `test_invariants.py` lifecycle assertions might need updating; investigation shows they do NOT (they exercise the direct score path, which keeps `classify_state`). Only `test_config.py` changes. The plan reflects the precise impact.

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to". Every code step shows full code.

**3. Type consistency:** `assign_relative_states(signals, board)` signature identical across Task 2 (def + tests) and Task 3 (import + call). `Signal` fields (`surprise`, `baseline_mean`, `state`) match `radar/models.py`. Tier thresholds `t1/t2` and the `new`/`hot`/`cooling`/`sustained` branch order are identical to the spec and the Global Constraints.
