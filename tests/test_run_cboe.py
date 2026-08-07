"""CBOE loop wiring in radar.run.main: the 404 vs. real-outage distinction and the
consecutive-failure circuit breaker (F2b/F2c) — see radar/options.py for the fetch-level
behaviour (404 -> "missing", other failures -> None) tested in test_options.py."""
import json

from radar.apewisdom import Aggregate


def _aggregates(n):
    return [Aggregate(ticker=f"T{i:02d}", name=f"Ticker {i}", mentions=100 - i,
                       mentions_24h_ago=10, upvotes=500, subreddit="all-stocks")
            for i in range(n)]


def _run(monkeypatch, tmp_path, option_stats_fn):
    import radar.run as run
    monkeypatch.setattr(run, "fetch_mentions", lambda cfg: _aggregates(12))
    monkeypatch.setattr(run.tradestie, "fetch_wsb", lambda cfg: [])
    monkeypatch.setattr(run, "fetch_short_ratios", lambda cfg, run_day: ({}, ""))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setattr(run.news, "headlines", lambda *a, **k: [])
    monkeypatch.setattr(run, "option_stats", option_stats_fn)
    out = tmp_path / "out"
    code = run.main(["--dry-run", "--no-email", "--out", str(out)])
    assert code == 0
    return json.loads((out / "data.json").read_text())


def test_missing_sentinel_no_warn_no_annotation_but_counts_as_hit(monkeypatch, tmp_path):
    import radar.degrade as degrade
    calls = []
    missing_ticker = {}

    def fake_option_stats(ticker, cfg):
        calls.append(ticker)
        if not missing_ticker:
            missing_ticker["t"] = ticker          # first ticker: e.g. crypto/small-cap 404
            return "missing"
        return {"pc_ratio": 0.5, "call_vol": 10, "put_vol": 5,
                "total_vol": 15, "total_oi": 100}

    payload = _run(monkeypatch, tmp_path, fake_option_stats)

    t = missing_ticker["t"]
    assert not any(e["what"] == "cboe options" and e["reason"] == t
                   for e in degrade.events())
    row = next(s for s in payload["signals"] if s["ticker"] == t)
    assert row["pc_ratio"] is None and row["uoa"] is False       # missing -> annotate nothing
    assert payload["health"]["sources"]["cboe"] == "ok"          # service responded -> not "down"


def test_breaker_trips_after_three_consecutive_nones_and_skips_rest(monkeypatch, tmp_path):
    import radar.degrade as degrade
    calls = []

    def fake_option_stats(ticker, cfg):
        calls.append(ticker)
        return None                                 # every ticker looks like an outage

    payload = _run(monkeypatch, tmp_path, fake_option_stats)

    assert len(calls) == 3                           # breaker stopped calling after 3
    assert any(e["what"] == "cboe options" and "after 3 consecutive failures" in e["reason"]
               for e in degrade.events())
    assert payload["health"]["sources"]["cboe"] == "down"        # zero hits -> down


def test_breaker_resets_on_success_between_failures(monkeypatch, tmp_path):
    import radar.degrade as degrade

    calls = []

    def fake_option_stats(ticker, cfg):
        calls.append(ticker)
        # two Nones, one success, then Nones again — never 3 IN A ROW, breaker must not trip
        idx = len(calls) - 1
        if idx in (0, 1, 3, 4):
            return None
        return {"pc_ratio": 0.5, "call_vol": 10, "put_vol": 5,
                "total_vol": 15, "total_oi": 100}

    payload = _run(monkeypatch, tmp_path, fake_option_stats)

    assert len(calls) == 10                           # all of cboe.top_n processed, no early break
    assert not any(e["what"] == "cboe options" and "after 3 consecutive failures" in e["reason"]
                   for e in degrade.events())
