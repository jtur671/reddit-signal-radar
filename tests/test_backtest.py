import json
import math
from datetime import date, timedelta

from radar.backtest import (trading_days, entry_index, window_return, excess_return,
                            spearman, quintile_table, rank_ic, event_study,
                            vol_quintiles, scorecard, power, REGIME_NOTES,
                            fetch_prices, run_backtest, _pricing_universe)

def _prices(series):     # {sym: {day: open}} -> full price dicts (close = open)
    return {s: {d: {"open": v, "close": v} for d, v in days.items()} for s, days in series.items()}

DAYS = ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-06", "2026-07-07",
        "2026-07-08", "2026-07-09", "2026-07-10"]

def _flat(v=100.0):
    return {d: v for d in DAYS}

def test_trading_days_and_entry_index():
    p = _prices({"SPY": _flat()})
    days = trading_days(p)
    assert days == DAYS
    assert entry_index(days, "2026-07-03") == 3          # weekend skipped -> Mon 07-06
    assert entry_index(days, "2026-07-01") == 1
    assert entry_index(days, "2026-07-10") is None       # nothing strictly after
    assert entry_index(days, "2026-06-01") == 0

def test_lookahead_gate_never_prices_signal_day():
    # THE invariant: entry is strictly after the signal day, so a same-day price move
    # can never flatter the signal. 2026-07-02 doubles; signal fired ON 07-02 must
    # enter at 07-03 (100.0) and see 0% -- not +100%.
    p = _prices({"AAA": {**_flat(), "2026-07-02": 200.0},
                 "SPY": _flat()})
    days = trading_days(p)
    i0 = entry_index(days, "2026-07-02")
    assert days[i0] == "2026-07-03"
    assert window_return(p, "AAA", days, i0, 1) == 0.0

def test_window_and_excess_return():
    up = {d: 100.0 + i for i, d in enumerate(DAYS)}      # ~+1%/day
    p = _prices({"AAA": up, "SPY": _flat()})
    days = trading_days(p)
    r = window_return(p, "AAA", days, 0, 1)
    assert abs(r - 0.01) < 1e-9
    assert abs(excess_return(p, "AAA", days, 0, 1) - 0.01) < 1e-9   # flat benchmark
    assert window_return(p, "AAA", days, 5, 99) is None  # off the end
    assert window_return(p, "MISSING", days, 0, 1) is None

def test_spearman_known_values():
    assert abs(spearman([1, 2, 3, 4], [10, 20, 30, 40]) - 1.0) < 1e-9
    assert abs(spearman([1, 2, 3, 4], [40, 30, 20, 10]) + 1.0) < 1e-9
    assert spearman([1, 1, 1], [1, 2, 3]) == 0.0         # degenerate -> 0, not crash

def test_quintiles_separate_good_from_bad():
    # 10 tickers, one signal day. Scores 1..10; forward return proportional to score.
    hist = {f"T{i}": {"2026-07-01": {"weighted": 1.0, "raw": 5, "authors": 0,
                                     "pct_bull": 0, "score": float(i), "state": "hot"}}
            for i in range(1, 11)}
    series = {f"T{i}": {d: 100.0 * (1 + 0.001 * i) ** n for n, d in enumerate(DAYS)}
              for i in range(1, 11)}
    series["SPY"] = _flat()
    p = _prices(series)
    days = trading_days(p)
    q = quintile_table(hist, p, days, horizon=1)
    assert q["n"] == 10
    assert q["q5"]["mean_excess"] > q["q1"]["mean_excess"]
    assert q["spread"] > 0

def test_rank_ic_positive_when_score_predicts():
    hist = {f"T{i}": {d: {"weighted": 1.0, "raw": 5, "authors": 0, "pct_bull": 0,
                          "score": float(i), "state": "hot"}
                      for d in DAYS[:5]}
            for i in range(1, 11)}
    series = {f"T{i}": {d: 100.0 * (1 + 0.001 * i) ** n for n, d in enumerate(DAYS)}
              for i in range(1, 11)}
    series["SPY"] = _flat()
    p = _prices(series)
    ic = rank_ic(hist, p, trading_days(p), horizon=1)
    assert ic["mean"] > 0.9 and ic["days"] >= 4

def test_event_study_counts_hot_transitions():
    hist = {"AAA": {"2026-07-01": {"weighted": 1, "raw": 5, "authors": 0, "pct_bull": 0,
                                   "score": 10.0, "state": "sustained"},
                    "2026-07-02": {"weighted": 9, "raw": 40, "authors": 0, "pct_bull": 0,
                                   "score": 90.0, "state": "hot"}}}   # transition -> 1 event
    p = _prices({"AAA": _flat(), "SPY": _flat()})
    es = event_study(hist, p, trading_days(p))
    assert es["n_events"] == 1
    assert "0" in es["car"] and "5" in es["car"]

def test_scorecard_grades_picks():
    plays = [{"date": "2026-07-01", "ticker": "AAA", "conviction": "high"},
             {"date": "2026-07-01", "ticker": "BBB", "conviction": "low"}]
    up = {d: 100.0 * (1.02 ** i) for i, d in enumerate(DAYS)}     # winner
    dn = {d: 100.0 * (0.98 ** i) for i, d in enumerate(DAYS)}     # loser
    p = _prices({"AAA": up, "BBB": dn, "SPY": _flat()})
    sc = scorecard(plays, p, trading_days(p))
    assert sc["n_picks"] == 2
    assert sc["win_rate_5d"] == 0.5
    assert sc["mean_excess_5d"] is not None
    assert sc["since"] == "2026-07-01"

def test_scorecard_excludes_crypto_picks():
    plays = [{"date": "2026-07-01", "ticker": "AAA", "conviction": "high"},
             {"date": "2026-07-01", "ticker": "ETH", "conviction": "high", "crypto": True}]
    up = {d: 100.0 * (1.02 ** i) for i, d in enumerate(DAYS)}     # winner
    dn = {d: 100.0 * (0.98 ** i) for i, d in enumerate(DAYS)}     # would tank the mean/win-rate
    p = _prices({"AAA": up, "ETH": dn, "SPY": _flat()})
    sc = scorecard(plays, p, trading_days(p))
    assert sc["n_picks"] == 1                                    # ETH not graded
    assert sc["excluded_crypto"] == 1
    assert all(r["ticker"] != "ETH" for r in sc["picks"])
    assert sc["win_rate_5d"] == 1.0                               # only AAA counts
    assert sc["mean_excess_5d"] > 0

def test_scorecard_excluded_crypto_zero_when_none():
    plays = [{"date": "2026-07-01", "ticker": "AAA", "conviction": "high"}]
    up = {d: 100.0 * (1.02 ** i) for i, d in enumerate(DAYS)}
    p = _prices({"AAA": up, "SPY": _flat()})
    sc = scorecard(plays, p, trading_days(p))
    assert sc["excluded_crypto"] == 0

def test_power_and_regime_notes():
    hist = {"AAA": {d: {"weighted": 1, "raw": 5, "authors": 0, "pct_bull": 0,
                        "score": 1.0, "state": "new"} for d in DAYS}}
    pw = power(hist)
    assert pw["days"] == len(DAYS) and pw["sufficient"] is False and pw["target_days"] == 150
    assert any("2026-08-07" in n["date"] for n in REGIME_NOTES)

def test_daily_scorecard_fail_soft_on_exception(monkeypatch):
    # A raising price fetch -> None + a degrade breadcrumb; the board must not care.
    import radar.run as run_mod
    from radar import degrade
    degrade.reset()
    monkeypatch.setattr("radar.run.load_picks",
                        lambda p: [{"date": "2026-08-01", "ticker": "AAA", "conviction": "high"}])
    def _boom(*a, **k):
        raise RuntimeError("yfinance down")
    monkeypatch.setattr("radar.backtest.fetch_prices", _boom)
    assert run_mod._daily_scorecard("2026-08-08") is None
    assert any(e["what"] == "daily scorecard" for e in degrade.events())

def test_daily_scorecard_none_when_no_prices(monkeypatch):
    # Non-empty log but empty price data -> None via the no-trading-days path, plus a
    # "daily scorecard" breadcrumb (a real, transient benchmark outage should surface).
    import radar.run as run_mod
    from radar import degrade
    degrade.reset()
    monkeypatch.setattr("radar.run.load_picks",
                        lambda p: [{"date": "2026-08-01", "ticker": "AAA", "conviction": "high"}])
    monkeypatch.setattr("radar.backtest.fetch_prices", lambda *a, **k: {})
    assert run_mod._daily_scorecard("2026-08-08") is None
    assert any(e["what"] == "daily scorecard" for e in degrade.events())

def test_daily_scorecard_unpriceable_pick_does_not_degrade_health(monkeypatch):
    # F1: one pick ticker (e.g. delisted/crypto) never prices while SPY does. Because
    # the plays log is append-only, this must NOT fire "backtest prices" -- that would
    # degrade health.status on every future daily run, forever, over one old pick.
    import radar.run as run_mod
    from radar import degrade
    degrade.reset()
    monkeypatch.setattr("radar.run.load_picks",
                        lambda p: [{"date": "2026-08-01", "ticker": "AAA", "conviction": "high"}])

    def _fake_fetch_prices(tickers, start, end, warn_missing=True):
        # Mirrors fetch_prices's own missing-ticker warn, gated the same way, so this
        # test actually exercises the warn_missing=False wiring rather than assuming it.
        prices = {"SPY": {"2026-08-01": {"open": 100.0, "close": 100.0},
                          "2026-08-08": {"open": 101.0, "close": 101.0}}}
        missing = [t for t in tickers if t not in prices]
        if missing and warn_missing:
            degrade.warn("backtest prices", f"{len(missing)} unpriced")
        return prices

    monkeypatch.setattr("radar.backtest.fetch_prices", _fake_fetch_prices)
    sc = run_mod._daily_scorecard("2026-08-08")
    assert sc is not None and sc["n_picks"] == 1
    assert not any(e["what"] == "backtest prices" for e in degrade.events())

def test_template_renders_scorecard_block():
    from radar.render import render_html
    from radar.run import _build_context
    ctx = _build_context([], [], "2026-08-08", 0,
                         scorecard={"n_picks": 3, "since": "2026-08-01",
                                    "mean_excess_10d": 0.021, "win_rate_10d": 0.67,
                                    "mean_excess_5d": 0.01, "win_rate_5d": 0.5,
                                    "picks": [], "disclaimer": "Hypothetical. Not advice."})
    html = render_html(**ctx)
    assert "Early Plays Track Record" in html and "+2.1%" in html

def test_template_hides_scorecard_when_absent():
    from radar.render import render_html
    from radar.run import _build_context
    html = render_html(**_build_context([], [], "2026-08-08", 0))
    assert "Early Plays Track Record" not in html

# ---------- fix round 1: event_study completeness/rebase, fetch_prices, run_backtest ----------

def _bdays(n, start="2026-01-05"):     # n business days (weekdays only) starting Monday
    d = date.fromisoformat(start)
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out

def _hot_transition(prev_day, hot_day):
    return {prev_day: {"weighted": 1, "raw": 5, "authors": 0, "pct_bull": 0,
                       "score": 1.0, "state": "sustained"},
            hot_day: {"weighted": 9, "raw": 40, "authors": 0, "pct_bull": 0,
                     "score": 90.0, "state": "hot"}}

def test_event_study_rebase_and_completeness():
    # AAA grows at a clean +1% log return/day; SPY flat -> every bar's excess is 0.01.
    # 40 trading days gives a fully complete default (-5..+20) window around i0=10.
    days_list = _bdays(40)
    signal_day = days_list[9]
    hist = {"AAA": _hot_transition(days_list[8], signal_day)}
    aaa = {d: 100.0 * math.exp(0.01 * i) for i, d in enumerate(days_list)}
    p = _prices({"AAA": aaa, "SPY": {d: 100.0 for d in days_list}})
    days = trading_days(p)
    es = event_study(hist, p, days)
    assert es["n_used"] == 1
    assert abs(es["car"]["-1"]) < 1e-9                      # rebased: -1 is the zero point
    # off=20 rebased == sum of bars off=0..20 (21 bars), NOT the raw 26-bar (-5..20) sum
    assert abs(es["car"]["20"] - 21 * 0.01) < 1e-6

def test_event_study_excludes_unpriced_ticker_from_averages():
    days_list = _bdays(40)
    signal_day = days_list[9]
    hist = {"AAA": _hot_transition(days_list[8], signal_day),
            "ZZZ": _hot_transition(days_list[8], signal_day)}   # ZZZ never gets priced below
    aaa = {d: 100.0 * math.exp(0.01 * i) for i, d in enumerate(days_list)}
    p = _prices({"AAA": aaa, "SPY": {d: 100.0 for d in days_list}})   # no ZZZ prices
    days = trading_days(p)
    es = event_study(hist, p, days)
    assert es["n_events"] == 2      # both transitions counted
    assert es["n_used"] == 1        # only the priced, complete one enters the averages

def test_event_study_excludes_incomplete_tail_event():
    # Signal too close to the end of the price series for the +20 post window to fit.
    days_list = _bdays(40)
    signal_day = days_list[35]
    hist = {"AAA": _hot_transition(days_list[34], signal_day)}
    aaa = {d: 100.0 * math.exp(0.01 * i) for i, d in enumerate(days_list)}
    p = _prices({"AAA": aaa, "SPY": {d: 100.0 for d in days_list}})
    days = trading_days(p)
    es = event_study(hist, p, days)
    assert es["n_events"] == 1
    assert es["n_used"] == 0        # incomplete window -> excluded, not zero-padded

def test_fetch_prices_skips_bad_row_keeps_good_rows(monkeypatch):
    import pandas as pd

    idx = pd.to_datetime(["2026-07-01", "2026-07-02", "2026-07-03"])
    df = pd.DataFrame({"Open": [99.0, "not-a-number", 101.0],
                       "Close": [100.0, 101.0, 102.0]}, index=idx)

    def fake_download(tickers, **kwargs):
        return df

    monkeypatch.setattr("yfinance.download", fake_download)
    out = fetch_prices(["AAA"], "2026-07-01", "2026-07-05")
    assert "2026-07-01" in out.get("AAA", {})
    assert "2026-07-03" in out["AAA"]
    assert "2026-07-02" not in out["AAA"]     # bad row skipped, not the whole ticker

def test_run_backtest_does_not_write_on_price_fetch_failure(tmp_path, monkeypatch):
    import radar.backtest as bt

    hist_path = tmp_path / "history.json"
    hist_path.write_text(json.dumps({"AAA": {"2026-07-01": {"weighted": 1, "raw": 5,
                                                             "authors": 0, "pct_bull": 0,
                                                             "score": 1.0, "state": "new"}}}))
    plays_path = tmp_path / "plays.json"
    plays_path.write_text(json.dumps({"picks": []}))
    out_path = tmp_path / "out" / "backtest.json"

    monkeypatch.setattr(bt, "fetch_prices", lambda tickers, start, end: {})
    result = bt.run_backtest(str(hist_path), str(plays_path), str(out_path))
    assert result["error"] == "price fetch failed"
    assert not out_path.exists()

# ---------- final-review fix wave: warn_missing, full pricing universe, vol_test n ----------

def test_fetch_prices_warn_missing_flag_gates_the_missing_tickers_event(monkeypatch):
    # An empty batch means every requested ticker comes back unpriced. With the default
    # (warn_missing=True) that fires "backtest prices"; with warn_missing=False it must not.
    import pandas as pd
    from radar import degrade

    monkeypatch.setattr("yfinance.download", lambda tickers, **kwargs: pd.DataFrame())

    degrade.reset()
    fetch_prices(["ZZZ"], "2026-07-01", "2026-07-05")
    assert any(e["what"] == "backtest prices" for e in degrade.events())

    degrade.reset()
    fetch_prices(["ZZZ"], "2026-07-01", "2026-07-05", warn_missing=False)
    assert not any(e["what"] == "backtest prices" for e in degrade.events())

def test_pricing_universe_includes_non_top_quintile_tickers():
    # 10 tickers, scores 1..10 on one day -> q5 (top quintile) is only T9/T10. The old
    # _board_universe restricted pricing to q5; the widened universe must include the
    # bottom-quintile tickers too, since q1-q4 need to be priced to grade fairly.
    hist = {f"T{i}": {"2026-07-01": {"weighted": 1.0, "raw": 5, "authors": 0,
                                     "pct_bull": 0, "score": float(i), "state": "new"}}
            for i in range(1, 11)}
    universe = _pricing_universe(hist)
    assert universe == set(hist.keys())
    assert "T1" in universe and "T2" in universe   # bottom quintile, previously excluded

def test_vol_quintiles_reports_mean_and_n():
    hist = {f"T{i}": {d: {"weighted": 1, "raw": 5, "authors": 0, "pct_bull": 0,
                          "score": float(i), "state": "hot"}
                      for d in DAYS[:1]}
            for i in range(1, 11)}
    series = {f"T{i}": {d: 100.0 * (1 + 0.002 * i) ** n for n, d in enumerate(DAYS)}
              for i in range(1, 11)}
    series["SPY"] = _flat()
    p = _prices(series)
    vt = vol_quintiles(hist, p, trading_days(p), horizon=3)
    for q in range(1, 6):
        block = vt[f"q{q}"]
        assert set(block.keys()) == {"mean", "n"}
        assert isinstance(block["n"], int) and block["n"] >= 0
        if block["n"] == 0:
            assert block["mean"] is None
        else:
            assert isinstance(block["mean"], float)

def test_run_backtest_artifact_has_universe_block(tmp_path, monkeypatch):
    import radar.backtest as bt

    hist_path = tmp_path / "history.json"
    hist_path.write_text(json.dumps({"AAA": {"2026-07-01": {"weighted": 1, "raw": 5,
                                                             "authors": 0, "pct_bull": 0,
                                                             "score": 1.0, "state": "new"}}}))
    plays_path = tmp_path / "plays.json"
    plays_path.write_text(json.dumps({"picks": []}))
    out_path = tmp_path / "out" / "backtest.json"

    def fake_fetch(tickers, start, end):
        return {t: {"2026-07-01": {"open": 100.0, "close": 100.0},
                    "2026-07-02": {"open": 101.0, "close": 101.0}} for t in tickers}

    monkeypatch.setattr(bt, "fetch_prices", fake_fetch)
    result = bt.run_backtest(str(hist_path), str(plays_path), str(out_path))
    assert result["universe"]["description"] == "all history tickers + logged picks + benchmarks"
    assert result["universe"]["n_tickers"] == result["price_coverage"]["requested"]
