from radar.models import Item, Mention, Signal

def test_item_roundtrip():
    it = Item(id="t3_x", kind="post", subreddit="wsb", author="u1",
              created_utc=1.0, text="$IREN to the moon", score=42, permalink="/x")
    assert it.kind == "post" and it.author == "u1"

def test_signal_defaults():
    s = Signal(ticker="IREN")
    assert s.mentions == 0 and s.distinct_authors == 0 and s.themes == []
