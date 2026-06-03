from radar.reddit_posts import parse_listing, top_posts, get_token

LISTING = {
    "data": {"children": [
        {"data": {"title": "VRT to the moon — AI datacenter play", "permalink": "/r/wallstreetbets/comments/abc/vrt/",
                  "score": 1240, "subreddit": "wallstreetbets"}},
        {"data": {"title": "", "permalink": "/r/x/y/"}},                 # no title -> skipped
        {"data": {"title": "no link here", "permalink": ""}},            # no permalink -> skipped
        {"data": {"title": "DD on Vertiv", "permalink": "/r/stocks/comments/def/dd/",
                  "score": 88, "subreddit": "stocks"}},
    ]}
}


def test_parse_listing_extracts_posts_and_full_urls():
    out = parse_listing(LISTING)
    assert [p["title"] for p in out] == ["VRT to the moon — AI datacenter play", "DD on Vertiv"]
    assert out[0]["url"] == "https://www.reddit.com/r/wallstreetbets/comments/abc/vrt/"
    assert out[0]["score"] == 1240 and out[0]["subreddit"] == "wallstreetbets"


def test_parse_listing_respects_limit_and_bad_input():
    assert len(parse_listing(LISTING, max_items=1)) == 1
    assert parse_listing({}) == [] and parse_listing("nope") == []


def test_top_posts_no_token_is_empty_no_network():
    assert top_posts("VRT", ["wallstreetbets"], None, "ua") == []   # fail-safe, never calls out


def test_get_token_missing_creds_returns_none():
    assert get_token("", "", "ua") is None
