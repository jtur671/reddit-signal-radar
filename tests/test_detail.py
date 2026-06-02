from radar.run import _history_series, _detail_blob
from radar.history import History
from radar.models import Signal


def _board_sig(ticker, **k):
    s = Signal(ticker=ticker, mentions=k.get("mentions", 100))
    s.themes = k.get("themes", ["AI Compute"])
    s.summary = k.get("summary", "why it's trending")
    s.subreddits = ["all-stocks"]
    s.vel_24h = 2.0
    return s


def _hist(days):
    h = History("x", {})
    for d, m in days:
        h.record(d, "AAA", weighted=m, raw=m, authors=0, pct_bull=0, score=1, state="new")
    return h


def test_history_series_window_and_order():
    h = _hist([("2025-01-01", 999), ("2026-05-31", 10), ("2026-06-01", 14)])  # ancient one excluded
    series = _history_series(h, "AAA", "2026-06-01", days=90)
    assert [p["d"] for p in series] == ["2026-05-31", "2026-06-01"]   # trimmed + chronological
    assert [p["m"] for p in series] == [10, 14]


def test_history_series_short():
    series = _history_series(_hist([("2026-06-01", 5)]), "AAA", "2026-06-01")
    assert len(series) < 3                                            # JS shows "building history"


def test_detail_blob_shape():
    board = [_board_sig("AAA")]
    blob = _detail_blob(board, _hist([("2026-06-01", 100)]), "2026-06-01")
    d = blob["AAA"]
    assert d["ticker"] == "AAA" and d["vel24"] == "2.0×"
    assert d["summary"] == "why it's trending" and d["subreddits"] == ["all-stocks"]
    assert isinstance(d["series"], list)


def test_detail_blob_has_why():
    s = _board_sig("AAA", mentions=300)
    s.vel_24h = 2.4; s.state = "hot"; s.surprise = 4.7; s.upvotes = 34720
    blob = _detail_blob([s], _hist([("2026-06-01", 300)]), "2026-06-01")
    why = blob["AAA"]["why"]
    assert "2.4×" in why and "300" in why and "AI Compute" in why and "34.7k upvotes" in why


def test_detail_blob_has_name_and_about():
    s = _board_sig("HPE")
    s.name = "Hewlett Packard Enterprise"
    s.about_desc = "American IT company"
    s.about_extract = "Hewlett Packard Enterprise is an American multinational IT company."
    blob = _detail_blob([s], _hist([("2026-06-01", 100)]), "2026-06-01")
    d = blob["HPE"]
    assert d["name"] == "Hewlett Packard Enterprise"
    assert d["about"].startswith("Hewlett Packard Enterprise")   # prefers extract
