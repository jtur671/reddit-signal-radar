import json, pathlib
from radar.news import finnhub_headlines, parse_finnhub, headlines

def test_parse_finnhub_from_fixture():
    raw = json.loads(pathlib.Path("tests/fixtures/finnhub_news.json").read_text())
    titles = parse_finnhub(raw, max_items=6)
    assert titles and all(isinstance(t, str) and t for t in titles)
    assert len(titles) <= 6

def test_parse_finnhub_never_raises():
    for raw in (None, {}, [], [{"nope": 1}], [{"headline": ""}], "x"):
        assert isinstance(parse_finnhub(raw), list)

def test_headlines_prefers_finnhub_falls_back_to_google(monkeypatch):
    import radar.news as news
    monkeypatch.setenv("FINNHUB_API_KEY", "k")
    monkeypatch.setattr(news, "finnhub_headlines", lambda *a, **k: ["FH headline"])
    assert headlines("AAPL", "Apple") == ["FH headline"]
    monkeypatch.setattr(news, "finnhub_headlines", lambda *a, **k: [])
    monkeypatch.setattr(news, "_google_headlines", lambda *a, **k: ["G headline"])
    assert headlines("AAPL", "Apple") == ["G headline"]

def test_headlines_no_key_goes_straight_to_google(monkeypatch):
    import radar.news as news
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    called = []
    monkeypatch.setattr(news, "finnhub_headlines",
                        lambda *a, **k: called.append(1) or [])
    monkeypatch.setattr(news, "_google_headlines", lambda *a, **k: ["G"])
    assert headlines("AAPL") == ["G"] and not called
