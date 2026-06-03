from types import SimpleNamespace
from radar.models import Signal
from radar.history import History
from radar.still_running import still_running


def _sig(ticker, state, velocity, mentions):
    s = Signal(ticker=ticker, mentions=mentions, state=state)
    s.velocity = velocity
    return s


def _hist(states_by_ticker):
    """states_by_ticker: {ticker: {day: state}} -> a real History."""
    data = {
        t: {d: {"weighted": 1.0, "raw": 1, "authors": 0,
                "pct_bull": 0, "score": 0, "state": st}
            for d, st in days.items()}
        for t, days in states_by_ticker.items()
    }
    return History("x", data)


def _cfg(lookback=3, max_items=5, cap=10):
    return SimpleNamespace(still_running=SimpleNamespace(
        lookback_days=lookback, max_items=max_items, velocity_cap=cap))


def test_qualifies_broke_out_alive_offboard():
    sig = _sig("MRVL", "sustained", velocity=2.0, mentions=931)
    hist = _hist({"MRVL": {"2026-06-02": "new"}})
    out = still_running([sig], hist, "2026-06-03", board=[], cfg=_cfg())
    assert [s.ticker for s in out] == ["MRVL"]
    assert out[0].days_running == 1


def test_excludes_new_today():
    sig = _sig("FOO", "new", 5.0, 500)
    hist = _hist({"FOO": {"2026-06-02": "new"}})
    assert still_running([sig], hist, "2026-06-03", [], _cfg()) == []


def test_excludes_cooling_today():
    sig = _sig("FOO", "cooling", 0.5, 500)
    hist = _hist({"FOO": {"2026-06-02": "hot"}})
    assert still_running([sig], hist, "2026-06-03", [], _cfg()) == []


def test_excludes_breakout_older_than_lookback():
    sig = _sig("FOO", "sustained", 2.0, 500)
    hist = _hist({"FOO": {"2026-05-30": "new"}})  # 4 days before, lookback 3
    assert still_running([sig], hist, "2026-06-03", [], _cfg(lookback=3)) == []


def test_includes_breakout_on_lookback_boundary():
    # cutoff is inclusive: with lookback=3 and run_day 2026-06-03, a breakout exactly
    # 3 days prior (2026-05-31, the cutoff edge) must still qualify; 2026-05-30 must not.
    sig = _sig("EDGE", "sustained", 2.0, 500)
    hist = _hist({"EDGE": {"2026-05-31": "new"}})
    out = still_running([sig], hist, "2026-06-03", [], _cfg(lookback=3))
    assert [s.ticker for s in out] == ["EDGE"]
    assert out[0].days_running == 3


def test_excludes_on_board():
    sig = _sig("MRVL", "sustained", 2.0, 931)
    hist = _hist({"MRVL": {"2026-06-02": "new"}})
    board = [_sig("MRVL", "sustained", 2.0, 931)]
    assert still_running([sig], hist, "2026-06-03", board, _cfg()) == []


def test_ranking_velocity_times_logvolume_with_cap():
    a = _sig("A", "sustained", 3.0, 100)     # 3 * log10(100)=2 -> 6
    b = _sig("B", "hot", 50.0, 1000)         # min(50,10)=10 * log10(1000)=3 -> 30
    hist = _hist({"A": {"2026-06-02": "new"}, "B": {"2026-06-02": "hot"}})
    out = still_running([a, b], hist, "2026-06-03", [], _cfg(cap=10))
    assert [s.ticker for s in out] == ["B", "A"]


def test_truncates_to_max_items():
    sigs = [_sig(f"T{i}", "sustained", 2.0, 100 + i) for i in range(8)]
    hist = _hist({f"T{i}": {"2026-06-02": "new"} for i in range(8)})
    out = still_running(sigs, hist, "2026-06-03", [], _cfg(max_items=5))
    assert len(out) == 5


def test_empty_when_nothing_qualifies():
    assert still_running([], _hist({}), "2026-06-03", [], _cfg()) == []
