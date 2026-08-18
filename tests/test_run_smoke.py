def test_dry_run_writes_dashboard(tmp_path, monkeypatch):
    import radar.run as run
    from radar.apewisdom import Aggregate
    monkeypatch.setattr(run, "fetch_mentions", lambda cfg: [
        Aggregate(ticker="IREN", name="Iris Energy", mentions=120,
                  mentions_24h_ago=40, upvotes=900, subreddit="all-stocks"),
        Aggregate(ticker="KEEL", name="Keel Infrastructure", mentions=80,
                  mentions_24h_ago=10, upvotes=400, subreddit="all-stocks"),
    ])
    monkeypatch.setattr(run.tradestie, "fetch_wsb", lambda cfg: [])  # stub live Tradestie
    monkeypatch.setattr(run, "fetch_short_ratios", lambda cfg, run_day: ({}, ""))
    monkeypatch.setattr(run, "option_stats", lambda ticker, cfg: None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")    # skip LLM
    monkeypatch.setattr(run.news, "headlines", lambda *a, **k: [])  # stub live Google News
    code = run.main(["--dry-run", "--out", str(tmp_path / "out"), "--no-email"])
    assert code == 0
    html = (tmp_path / "out" / "index.html").read_text()
    assert "IREN" in html and "KEEL" in html      # populated board from aggregates


def test_dry_run_writes_signals_and_weights(tmp_path, monkeypatch):
    """F5 — a full offline run wires the composite pipeline end to end: data.json's
    `signals` array (one entry per board row, ticker/composite/components) and the raw
    `weights` config it was blended against (summing to ~1.0)."""
    import json
    import radar.run as run
    from radar.apewisdom import Aggregate
    monkeypatch.setattr(run, "fetch_mentions", lambda cfg: [
        Aggregate(ticker="IREN", name="Iris Energy", mentions=120,
                  mentions_24h_ago=40, upvotes=900, subreddit="all-stocks"),
        Aggregate(ticker="KEEL", name="Keel Infrastructure", mentions=80,
                  mentions_24h_ago=10, upvotes=400, subreddit="all-stocks"),
    ])
    monkeypatch.setattr(run.tradestie, "fetch_wsb", lambda cfg: [])  # no live network in tests
    monkeypatch.setattr(run, "fetch_short_ratios", lambda cfg, run_day: ({}, ""))
    monkeypatch.setattr(run, "fetch_cramer", lambda cfg, run_day: {})
    monkeypatch.setattr(run, "option_stats", lambda ticker, cfg: None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")    # skip LLM
    monkeypatch.setattr(run.news, "headlines", lambda *a, **k: [])  # no live Google News in tests

    out = tmp_path / "out"
    code = run.main(["--dry-run", "--no-email", "--out", str(out)])
    assert code == 0
    data = json.loads((out / "data.json").read_text())

    assert isinstance(data["signals"], list) and len(data["signals"]) == len(data["board"])
    assert {row["ticker"] for row in data["signals"]} == {"IREN", "KEEL"}
    for row in data["signals"]:
        assert {"ticker", "composite", "components"} <= row.keys()
        assert isinstance(row["components"], dict)

    assert isinstance(data["weights"], dict) and data["weights"]
    assert abs(sum(data["weights"].values()) - 1.0) < 1e-6


def test_run_maps_titles_and_reports_the_source(monkeypatch, tmp_path):
    """The map reaches about.describe, and the source reports itself like every other.

    IREN is mapped, KEEL is not: the exact mapped title is what gets fetched, and the
    unmapped ticker makes NO request at all (the anti-fuzzy guarantee, end to end)."""
    import json
    import radar.run as run
    from radar.apewisdom import Aggregate
    monkeypatch.setattr(run, "fetch_mentions", lambda cfg: [
        Aggregate(ticker="IREN", name="Iris Energy", mentions=120,
                  mentions_24h_ago=40, upvotes=900, subreddit="all-stocks"),
        Aggregate(ticker="KEEL", name="Keel Infrastructure", mentions=80,
                  mentions_24h_ago=10, upvotes=400, subreddit="all-stocks"),
    ])
    monkeypatch.setattr(run.tradestie, "fetch_wsb", lambda cfg: [])  # no live network in tests
    monkeypatch.setattr(run, "fetch_short_ratios", lambda cfg, run_day: ({}, ""))
    monkeypatch.setattr(run, "fetch_cramer", lambda cfg, run_day: {})
    monkeypatch.setattr(run, "option_stats", lambda ticker, cfg: None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")    # skip LLM
    monkeypatch.setattr(run.news, "headlines", lambda *a, **k: [])  # no live Google News in tests

    fetched = []
    monkeypatch.setattr(run.tickermap, "fetch_ticker_map",
                        lambda cfg, run_day: {"IREN": "IREN Limited"})
    monkeypatch.setattr(run.about, "fetch_summary",
                        lambda title, ua="x": fetched.append(title) or {
                            "desc": "d", "extract": "e", "title": title})

    out = tmp_path / "out"
    code = run.main(["--dry-run", "--no-email", "--out", str(out)])
    assert code == 0
    health = json.loads((out / "health.json").read_text())
    assert "tickermap" in health["sources"]
    assert health["sources"]["tickermap"] == "ok"
    assert fetched == ["IREN Limited"], "mapped title fetched; unmapped ticker not requested"


def test_run_reports_tickermap_down_when_the_map_is_empty(monkeypatch, tmp_path):
    """Fails soft and says so: an empty map still publishes a board, with a red LED."""
    import json
    import radar.run as run
    from radar.apewisdom import Aggregate
    monkeypatch.setattr(run, "fetch_mentions", lambda cfg: [
        Aggregate(ticker="IREN", name="Iris Energy", mentions=120,
                  mentions_24h_ago=40, upvotes=900, subreddit="all-stocks"),
    ])
    monkeypatch.setattr(run.tradestie, "fetch_wsb", lambda cfg: [])
    monkeypatch.setattr(run, "fetch_short_ratios", lambda cfg, run_day: ({}, ""))
    monkeypatch.setattr(run, "fetch_cramer", lambda cfg, run_day: {})
    monkeypatch.setattr(run, "option_stats", lambda ticker, cfg: None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setattr(run.news, "headlines", lambda *a, **k: [])
    monkeypatch.setattr(run.tickermap, "fetch_ticker_map", lambda cfg, run_day: {})

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    health = json.loads((out / "health.json").read_text())
    assert health["sources"]["tickermap"] == "down"
    assert "IREN" in (out / "index.html").read_text()      # board still publishes


def test_footer_leds_render_the_tickermap_source(monkeypatch, tmp_path):
    """Task 5 Step 7, verified by rendering rather than assumed: the dashboard's data-
    sources footer is a generic `for name, st in sources.items()` loop, so a new source
    gets its LED with no template change. This test is what proves that claim."""
    import radar.run as run
    from radar.apewisdom import Aggregate
    monkeypatch.setattr(run, "fetch_mentions", lambda cfg: [
        Aggregate(ticker="IREN", name="Iris Energy", mentions=120,
                  mentions_24h_ago=40, upvotes=900, subreddit="all-stocks"),
    ])
    monkeypatch.setattr(run.tradestie, "fetch_wsb", lambda cfg: [])
    monkeypatch.setattr(run, "fetch_short_ratios", lambda cfg, run_day: ({}, ""))
    monkeypatch.setattr(run, "fetch_cramer", lambda cfg, run_day: {})
    monkeypatch.setattr(run, "option_stats", lambda ticker, cfg: None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setattr(run.news, "headlines", lambda *a, **k: [])
    monkeypatch.setattr(run.tickermap, "fetch_ticker_map", lambda cfg, run_day: {})

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    html = (out / "index.html").read_text()
    assert "tickermap" in html and "tickermap · down" in html
