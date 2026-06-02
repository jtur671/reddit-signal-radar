from datetime import datetime, timezone

from radar.news import build_query, parse_news

NOW = datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc)

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>HPE skyrockets 30% on biggest earnings beat since 2018</title>
  <pubDate>Mon, 01 Jun 2026 14:00:00 GMT</pubDate></item>
<item><title>HPE stock hits record high on Nvidia server launch</title>
  <pubDate>Tue, 02 Jun 2026 09:00:00 GMT</pubDate></item>
<item><title>An ancient unrelated HPE story</title>
  <pubDate>Mon, 01 Jan 2024 09:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_build_query_uses_ticker_and_name():
    q = build_query("HPE", "Hewlett Packard Enterprise")
    assert "HPE" in q and "Hewlett" in q and "stock" in q


def test_parse_news_returns_recent_titles():
    out = parse_news(RSS, now=NOW)
    assert out[0].startswith("HPE skyrockets")
    assert any("record high" in t for t in out)


def test_parse_news_drops_stale_items():
    out = parse_news(RSS, now=NOW, max_age_days=10)
    assert not any("ancient" in t for t in out)        # 2024 item filtered out


def test_parse_news_respects_max_items():
    assert len(parse_news(RSS, now=NOW, max_items=1)) == 1


def test_parse_news_malformed_is_empty():
    assert parse_news("<not xml") == []


def test_summarize_returns_blank_without_headlines(monkeypatch):
    from radar.sentiment import summarize
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-x")
    assert summarize("HPE", [], "tech") == ""          # no headlines -> no catalyst claim
