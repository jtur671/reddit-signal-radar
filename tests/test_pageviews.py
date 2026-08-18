import json
import math
from pathlib import Path

import pytest

import radar.pageviews as pv
from radar import degrade


@pytest.fixture(autouse=True)
def _clear_degrade():
    # House pattern (see tests/test_health.py, tests/test_tickermap.py): degrade has no
    # clear() -- reset() is the established reset mechanism.
    degrade.reset()
    yield


def _flat(n, value):
    return [value] * n


def test_ratio_one_is_fifty():
    assert pv.spike_score(_flat(29, 100)) == 50.0


def test_anchors():
    """Anchors verified against the spec: 2x -> 75, 4x -> 100, 0.25x -> 0."""
    assert pv.spike_score(_flat(28, 100) + [200]) == 75.0
    assert pv.spike_score(_flat(28, 100) + [400]) == 100.0
    assert pv.spike_score(_flat(28, 100) + [25]) == 0.0


def test_clamps_beyond_two_log_units():
    assert pv.spike_score(_flat(28, 100) + [800]) == 100.0
    assert pv.spike_score(_flat(28, 100) + [10]) == 0.0


def test_uses_median_not_mean():
    """A single prior spike must not suppress today's score. Mean of this baseline is
    ~132, median is 100 -- with a mean the score would be visibly lower."""
    baseline = _flat(27, 100) + [1000]
    assert pv.spike_score(baseline + [200]) == 75.0


def test_none_when_baseline_too_thin():
    """A near-zero baseline makes the ratio explode: 2 views -> 12 would score 100.
    A name with no meaningful Wikipedia traffic has no attention signal."""
    assert pv.spike_score(_flat(28, 5) + [50]) is None


def test_none_when_too_few_days():
    assert pv.spike_score(_flat(15, 100) + [200]) is None


def test_none_on_empty_or_junk():
    for junk in ([], None, [100]):
        assert pv.spike_score(junk) is None


def test_zero_current_with_healthy_baseline_scores_zero():
    """Attention collapsing to zero against a healthy baseline is a real 0.0 -- 'nothing
    is happening' -- not None, which means 'no signal at all'. None would trigger the
    composite's renormalize-around-absence path, which is the wrong claim here."""
    assert pv.spike_score(_flat(28, 100) + [0]) == 0.0


def test_live_probe_regression():
    """Measured 2026-08-17: TSLA current 2554 against a 2816.5 median -> 46.47."""
    series = _flat(14, 2816) + _flat(14, 2817) + [2554]
    assert pv.spike_score(series) == 46.47


def test_unmapped_ticker_makes_no_request(monkeypatch):
    """The E2a anti-fuzzy guarantee holding at the E2 boundary. Assert the CALL COUNT:
    a missing entry could otherwise mean 'fetched and failed', which is different."""
    calls = []
    monkeypatch.setattr(pv, "_get_series", lambda *a, **k: calls.append(a))
    scores, raw = pv.fetch_attention({}, ["MVIS"], "2026-08-17")
    assert calls == []
    assert scores == {} and raw == {}


def test_maps_ticker_through_the_exact_title(monkeypatch):
    seen = {}
    def fake(title, start, end):
        seen["title"] = title
        return [100] * 28 + [200]
    monkeypatch.setattr(pv, "_get_series", fake)
    scores, raw = pv.fetch_attention({"TSLA": "Tesla, Inc."}, ["TSLA"], "2026-08-17")
    assert seen["title"] == "Tesla, Inc."
    assert scores["TSLA"] == 75.0
    assert raw["TSLA"] == 200


def test_one_ticker_failing_does_not_take_down_the_rest(monkeypatch):
    def fake(title, start, end):
        return None if title == "Bad" else [100] * 28 + [200]
    monkeypatch.setattr(pv, "_get_series", fake)
    scores, _ = pv.fetch_attention({"A": "Bad", "B": "Good"}, ["A", "B"], "2026-08-17")
    assert "A" not in scores and scores["B"] == 75.0
    # radar/degrade.py's own docstring is about exactly this regression: a fail-soft
    # path that goes silent. Deleting the warn() call must not leave the suite green.
    assert any(e["what"] == "wikimedia" for e in degrade.events())


def test_thin_baseline_is_absent_not_zero(monkeypatch):
    """None from spike_score must not become 0.0 -- a real zero says 'collapsed
    attention', absence says 'no signal'. composite.py renormalizes around absence."""
    monkeypatch.setattr(pv, "_get_series", lambda *a, **k: [2] * 28 + [12])
    scores, raw = pv.fetch_attention({"T": "Title"}, ["T"], "2026-08-17")
    assert "T" not in scores
    assert raw["T"] == 12, "raw views still published even when unscored"


def test_parse_series_reads_views_in_order():
    """Fed OUT of order, so an implementation that just appends in iteration order (and
    ignores the timestamp) fails this -- the guarantee under test is the sort, not
    incidental input ordering."""
    raw = {"items": [{"timestamp": "2026081600", "views": 30},
                     {"timestamp": "2026081400", "views": 10},
                     {"timestamp": "2026081500", "views": 20}]}
    assert pv.parse_series(raw) == [("2026081400", 10), ("2026081500", 20),
                                     ("2026081600", 30)]


def test_parse_series_never_raises():
    for junk in (None, {}, {"items": "nope"}, {"items": [{"views": "x"}]}):
        assert pv.parse_series(junk) == []


def test_get_series_uses_all_access_user_and_a_real_user_agent(monkeypatch):
    """`_get_series` is the private transport and stub seam, but every other test stubs
    it away entirely -- so the URL template, the User-Agent header, the status-code
    guard, and the parsing were, until now, executed by NO test. This is the test that
    would catch someone "simplifying" all-access/user/ to all-access/all-agents/ (a 32%
    bot-inflation regression) -- every fetch-level test would still pass, only this one
    inspects the real request."""
    fixture = json.loads(Path("tests/fixtures/pageviews_tsla.json").read_text())
    captured = {}
    class Resp:
        status_code = 200
        def json(self):
            return fixture
    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return Resp()
    monkeypatch.setattr(pv.requests, "get", fake_get)
    series = pv._get_series("Tesla, Inc.", "20260712", "20260816")
    assert "/all-access/user/" in captured["url"]
    assert captured["headers"]["User-Agent"], "empty UA gives Wikimedia a 403"
    assert len(series) == 29
    assert pv.spike_score(series) == 46.47


def test_get_series_rejects_a_stale_tail(monkeypatch):
    """`current = series[-1]` is only safe to treat as D-1 if the freshest day Wikimedia
    actually returned IS D-1. If Wikimedia has not yet published D-1 (or omitted a day),
    the tail is stale and every downstream score would be silently computed against the
    wrong day while still looking well-formed. Fail closed instead: a mismatched tail
    makes _get_series return None (the existing failure path), so the ticker ends up
    absent from scores, not silently wrong."""
    fixture = json.loads(Path("tests/fixtures/pageviews_tsla.json").read_text())
    fixture["items"][-1]["timestamp"] = "2026081500"  # requested end is 2026-08-16 (D-2)
    class Resp:
        status_code = 200
        def json(self):
            return fixture
    monkeypatch.setattr(pv.requests, "get", lambda *a, **k: Resp())

    assert pv._get_series("Tesla, Inc.", "20260712", "20260816") is None

    scores, raw = pv.fetch_attention({"TSLA": "Tesla, Inc."}, ["TSLA"], "2026-08-17")
    assert "TSLA" not in scores
    assert "TSLA" not in raw
    assert any(e["what"] == "wikimedia" for e in degrade.events())
