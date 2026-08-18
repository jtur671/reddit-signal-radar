import json
from radar.history import History

def test_update_and_baseline(tmp_path):
    p = tmp_path/"h.json"; p.write_text("{}")
    h = History.load(p)
    for day, val in [("2026-05-29",10),("2026-05-30",12),("2026-05-31",11)]:
        h.record(day, "IREN", weighted=val, raw=val, authors=val, pct_bull=60, score=1, state="hot")
    mean, std = h.baseline("IREN", before="2026-06-01", days=90, alpha=0.3)
    assert mean > 0 and std >= 0

def test_baseline_honors_days_window(tmp_path):
    # An ancient spike outside the trailing `days` window must NOT pollute the
    # baseline, even if prune() hasn't run yet (anti-staleness: 90-day window
    # enforced inside baseline, not only on disk).
    p = tmp_path/"h.json"; p.write_text("{}")
    h = History.load(p)
    h.record("2025-01-01","IREN",1000,1000,1000,50,1,"hot")   # far outside 90d
    h.record("2026-05-31","IREN",10,10,10,50,1,"hot")          # in-window
    mean, std = h.baseline("IREN", before="2026-06-01", days=90, alpha=0.3)
    assert mean == 10.0 and std == 0.0   # only the in-window day counts

def test_unknown_ticker_baseline_is_zero(tmp_path):
    h = History.load((tmp_path/"h.json")); (tmp_path/"h.json").write_text("{}")
    assert h.baseline("ZZZ", before="2026-06-01", days=90, alpha=0.3) == (0.0, 0.0)

def test_prune_drops_old_days(tmp_path):
    p = tmp_path/"h.json"; p.write_text("{}")
    h = History.load(p)
    h.record("2026-01-01","IREN",1,1,1,50,1,"hot")
    h.record("2026-06-01","IREN",5,5,5,50,1,"hot")
    h.prune(keep_through="2026-06-01", days=90)
    assert "2026-01-01" not in h.days_for("IREN")

def test_record_is_idempotent_per_day(tmp_path):
    p = tmp_path/"h.json"; p.write_text("{}")
    h = History.load(p)
    h.record("2026-06-01","IREN",5,5,5,50,1,"hot")
    h.record("2026-06-01","IREN",9,9,9,50,1,"hot")  # rerun same day overwrites
    assert h.days_for("IREN")["2026-06-01"]["weighted"] == 9


# --- load fails SOFT, like every other production-state reader on this branch ---------

import pytest
from radar import degrade


@pytest.fixture(autouse=True)
def _clear_degrade():
    # House pattern (tests/test_health.py, tests/test_tickermap.py, tests/test_pageviews.py).
    degrade.reset()
    yield


def test_a_truncated_history_does_not_kill_the_run(tmp_path):
    """`History.load` was the only production-state reader on this branch that failed
    HARD: a bare `json.loads(p.read_text())` with no `try`. Every snapshot reader E2
    added (about.load_cache, tickermap._snapshot_map, short_interest._read_snapshot)
    warns and returns nothing; this one raised, and `history.save()` is a bare
    truncate-then-write, so one interrupted daily job leaves a torn file that then
    bricks EVERY subsequent run until a human hand-edits the data branch.

    Empty is safer than crashing at all three consumers, checked rather than assumed:
      - score._finalize -> baseline() (0.0, 0.0) -> the documented brand-new/INV-8 path,
        which is exactly what a genuine day-1 cold start already produces;
      - still_running -> days_for() {} -> an empty lane, degraded but not wrong;
      - backtest.run_backtest -> no `all_days` -> {"error": "no history"} -> main()
        returns 1, so the weekly workflow fails BEFORE `cp -f out/backtest.json`
        and the last good artifact on the data branch is never clobbered."""
    p = tmp_path / "h.json"
    p.write_text('{"IREN": {"2026-08-1')            # killed mid-write
    h = History.load(p)

    assert h.data == {}
    assert h.baseline("IREN", before="2026-08-17", days=90, alpha=0.3) == (0.0, 0.0)
    assert h.days_for("IREN") == {}
    assert any("history" in e["what"] for e in degrade.events()), \
        "silently empty history is worse than a crash — the warn is what makes it visible"


def test_a_history_that_is_not_an_object_is_refused(tmp_path):
    """Valid JSON is not enough. A top-level list or string parses cleanly and then
    detonates later at `self.data.get(ticker, {})` — past every fail-soft boundary,
    inside the scoring loop. Refused at the door instead, like tickermap._snapshot_map's
    `isinstance(m, dict)` check."""
    for junk in ('[1, 2, 3]', '"a string"', 'null', '42'):
        degrade.reset()
        p = tmp_path / "h.json"
        p.write_text(junk)
        h = History.load(p)
        assert h.data == {}, f"{junk} must not become the history"
        assert h.days_for("IREN") == {}
        assert degrade.events(), f"{junk} was swallowed silently"


def test_an_absent_or_empty_history_is_a_cold_start_not_a_problem(tmp_path):
    """The other direction, and the one that keeps the warn meaningful: day 1 has no
    file, and an empty file is what a fresh data branch holds. Neither is corruption,
    so neither may cry degradation — a warn that fires every cold start is noise, and
    noise is how the real one gets ignored."""
    assert History.load(tmp_path / "nope.json").data == {}
    assert degrade.events() == []
    for blank in ("", "   \n"):
        p = tmp_path / "h.json"
        p.write_text(blank)
        assert History.load(p).data == {}
        assert degrade.events() == []


def test_a_recovered_history_is_still_writable(tmp_path):
    """Returning empty is only safe if the object is a WORKING History — the run goes on
    to record() and save() against it. A corrupt file is replaced by a valid one; the
    prior content is unrecoverable by definition (it did not parse), and the data branch
    keeps every previous day's commit if it is ever wanted."""
    p = tmp_path / "h.json"
    p.write_text("{not json")
    h = History.load(p)
    h.record("2026-08-17", "IREN", weighted=5, raw=5, authors=2, pct_bull=60,
             score=1.0, state="hot")
    h.save()
    assert json.loads(p.read_text())["IREN"]["2026-08-17"]["weighted"] == 5


def test_load_reads_the_file_exactly_once(tmp_path, monkeypatch):
    """The old body called `p.read_text()` TWICE — once for the `.strip()` emptiness
    test and once for `json.loads` — against a file another process is mid-write on.
    Two reads of a moving target can disagree: the first sees content, the second sees
    a different half. One read, then decide."""
    from pathlib import Path as _P
    p = tmp_path / "h.json"
    p.write_text('{"IREN": {}}')
    reads = []
    real = _P.read_text
    monkeypatch.setattr(_P, "read_text", lambda self, *a, **k: reads.append(self) or real(self, *a, **k))
    assert History.load(p).data == {"IREN": {}}
    assert len(reads) == 1, f"read the history {len(reads)} times"
