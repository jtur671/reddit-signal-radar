def test_dry_run_writes_dashboard(tmp_path, monkeypatch):
    import radar.run as run
    from radar.apewisdom import Aggregate
    monkeypatch.setattr(run, "fetch_mentions", lambda cfg: [
        Aggregate(ticker="IREN", name="Iris Energy", mentions=120,
                  mentions_24h_ago=40, upvotes=900, subreddit="all-stocks"),
        Aggregate(ticker="KEEL", name="Keel Infrastructure", mentions=80,
                  mentions_24h_ago=10, upvotes=400, subreddit="all-stocks"),
    ])
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")    # skip LLM
    monkeypatch.setattr(run.news, "headlines", lambda *a, **k: [])  # no live Google News in tests
    code = run.main(["--dry-run", "--out", str(tmp_path / "out"), "--no-email"])
    assert code == 0
    html = (tmp_path / "out" / "index.html").read_text()
    assert "IREN" in html and "KEEL" in html      # populated board from aggregates
