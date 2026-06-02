import json
import pathlib

from radar.apewisdom import parse_feed, fetch_mentions, Aggregate


def test_parse_feed_from_fixture():
    raw = json.loads(pathlib.Path("tests/fixtures/apewisdom.json").read_text())
    aggs = parse_feed(raw, source="all-stocks")
    assert len(aggs) >= 1
    a = aggs[0]
    assert a.ticker == "SPCE" and a.mentions > 0 and a.subreddit == "all-stocks"
    assert isinstance(a.mentions_24h_ago, int) and a.upvotes > 0


def test_parse_feed_strips_crypto_suffix_and_handles_missing():
    raw = {"results": [
        {"ticker": "AAA", "mentions": 50, "upvotes": 100, "mentions_24h_ago": 10, "name": "A Co"},
        {"ticker": "BTC.X", "mentions": 9, "upvotes": 4, "mentions_24h_ago": 3},  # crypto suffix
        {"ticker": "BBB"},                       # almost empty -> safe defaults
        {"mentions": 5},                         # no ticker -> dropped
        "garbage",                               # non-dict -> dropped
    ]}
    by = {a.ticker: a for a in parse_feed(raw, source="x")}
    assert by["AAA"].mentions == 50
    assert "BTC" in by and "BTC.X" not in by     # .X stripped to bare symbol
    assert by["BBB"].mentions == 0 and by["BBB"].mentions_24h_ago == 0
    assert len(by) == 3                          # AAA, BTC, BBB (no-ticker + garbage dropped)


def test_parse_feed_never_raises_on_garbage():
    for raw in [{}, {"results": None}, {"results": "x"}, None]:
        assert parse_feed(raw, source="x") == []


def test_fetch_merges_filters(monkeypatch):
    import radar.apewisdom as aw
    pages = {
        "all-stocks": {"results": [{"ticker": "NVDA", "mentions": 10, "upvotes": 5, "mentions_24h_ago": 4}]},
        "all-crypto": {"results": [
            {"ticker": "BTC.X", "mentions": 7, "upvotes": 3, "mentions_24h_ago": 2},
            {"ticker": "NVDA", "mentions": 1, "upvotes": 1, "mentions_24h_ago": 0},
        ]},
    }

    def fake_get(url, ua, retries, sleep_s):
        for f in pages:
            if f"/{f}/page/1" in url:
                return pages[f]
        return None                              # page 2+ -> stop paging

    monkeypatch.setattr(aw, "_get", fake_get)
    monkeypatch.setattr(aw.time, "sleep", lambda *_a, **_k: None)
    cfg = type("C", (), {})()
    cfg.apewisdom = type("A", (), {"filters": ["all-stocks", "all-crypto"], "max_pages": 2,
                                   "user_agent": "x", "max_retries": 1, "sleep_seconds": 0})
    aggs = {a.ticker: a for a in fetch_mentions(cfg)}
    assert aggs["BTC"].mentions == 7             # crypto suffix stripped
    assert aggs["NVDA"].mentions == 11           # summed across filters (10 + 1)
