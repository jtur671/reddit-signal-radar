import json, pathlib
from radar.fetch import parse_listing

def test_parse_listing_to_items():
    raw = json.loads((pathlib.Path("tests/fixtures/listing.json")).read_text())
    items = parse_listing(raw, kind="post")
    assert len(items) >= 1
    it = items[0]
    assert it.kind == "post" and it.subreddit and isinstance(it.created_utc, float)

def test_parse_listing_handles_deleted_and_missing():
    raw = {"data": {"children": [
        {"data": {"id": "a", "subreddit": "x", "author": None,
                  "created_utc": 1.0, "title": "T", "selftext": "$GME", "score": 3,
                  "permalink": "/a"}},
        {"data": {"id": "b"}},   # almost-empty -> must not crash
    ]}}
    items = parse_listing(raw, kind="post")
    assert items[0].author == "[deleted]"
    assert any(i.id == "b" for i in items)   # tolerated, defaults filled
