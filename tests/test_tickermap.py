import json
from pathlib import Path

import radar.tickermap as tm

RAW = json.loads(Path("tests/fixtures/wikidata_rows.json").read_text())


def test_plain_row_maps_ticker_to_title():
    assert tm.parse_rows(RAW)["AAPL"] == "Apple Inc."


def test_deprecated_rank_is_dropped():
    """AAL has a DeprecatedRank row for Anglo American; the live row must win."""
    assert tm.parse_rows(RAW)["AAL"] == "American Airlines Group"


def test_past_end_date_dropped_when_a_live_alternative_exists():
    """Google's listing ended 2016-01-01 and Alphabet's has no end date."""
    assert tm.parse_rows(RAW)["GOOG"] == "Alphabet Inc."


def test_sole_statement_is_kept_even_when_ended():
    """The proviso: an ended statement survives when it is the ONLY one for that
    ticker. Without this, every historical-only listing silently vanishes."""
    assert tm.parse_rows(RAW)["BBBY"] == "Bed Bath & Beyond"


def test_unresolved_same_family_ambiguity_is_omitted_not_guessed():
    """DOW has two live, same-rank candidates. parse_rows must NOT pick one at
    random -- the override file is what resolves these."""
    assert "DOW" not in tm.parse_rows(RAW)


def test_parse_rows_never_raises_on_junk():
    for junk in (None, {}, {"results": {}}, {"results": {"bindings": "nope"}},
                 {"results": {"bindings": [{"ticker": {}}]}}):
        assert tm.parse_rows(junk) == {}
