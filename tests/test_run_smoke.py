def test_dry_run_writes_dashboard(tmp_path, monkeypatch):
    import radar.run as run
    from radar.models import Item
    monkeypatch.setattr(run, "fetch_subreddit",
        lambda sub, cfg: [Item(f"{sub}{i}","comment",sub,f"u{i}", run.clock.now_utc()-3600,
                               "$IREN $IREN moon calls", 5, "/p") for i in range(6)])
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")    # skip LLM
    code = run.main(["--dry-run", "--out", str(tmp_path/"out"),
                     "--subreddits", "stocks", "--no-email"])
    assert code == 0
    assert (tmp_path/"out"/"index.html").exists()
