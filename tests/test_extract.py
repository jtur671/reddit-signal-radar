from radar.universe import Universe
from radar.models import Item
from radar.extract import extract_mentions

def U():
    return Universe(symbols={"IREN","HIVE","GME","BTC","AI"}, stopwords={"DD","YOLO","AI","CEO"})

def item(text, id="t1", author="u1"):
    return Item(id=id, kind="comment", subreddit="wsb", author=author,
                created_utc=1.0, text=text, score=1, permalink="/p")

def test_cashtag_always_trusted_even_if_stopword():
    m = extract_mentions([item("buying $AI and $IREN")], U())
    assert {x.ticker for x in m} == {"AI", "IREN"}

def test_bareword_must_be_in_universe_and_not_stopword():
    m = extract_mentions([item("my DD says IREN moons, CEO agrees, AI hype")], U())
    assert {x.ticker for x in m} == {"IREN"}

def test_lowercase_barewords_ignored():
    m = extract_mentions([item("i like iren and gme lol")], U())
    assert m == []

def test_one_mention_per_ticker_per_item():
    m = extract_mentions([item("GME GME $GME gme")], U())
    assert len([x for x in m if x.ticker == "GME"]) == 1
