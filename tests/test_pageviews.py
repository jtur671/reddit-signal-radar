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
    scores, raw, failed = pv.fetch_attention({}, ["MVIS"], "2026-08-17")
    assert calls == []
    assert scores == {} and raw == {}
    assert failed == 0, "nothing was asked, so nothing failed — the LED reads unused"


def test_maps_ticker_through_the_exact_title(monkeypatch):
    seen = {}
    def fake(title, start, end):
        seen["title"] = title
        return [100] * 28 + [200]
    monkeypatch.setattr(pv, "_get_series", fake)
    scores, raw, _failed = pv.fetch_attention({"TSLA": "Tesla, Inc."}, ["TSLA"], "2026-08-17")
    assert seen["title"] == "Tesla, Inc."
    assert scores["TSLA"] == 75.0
    assert raw["TSLA"] == 200


def test_one_ticker_failing_does_not_take_down_the_rest(monkeypatch):
    def fake(title, start, end):
        return None if title == "Bad" else [100] * 28 + [200]
    monkeypatch.setattr(pv, "_get_series", fake)
    scores, _raw, _failed = pv.fetch_attention({"A": "Bad", "B": "Good"}, ["A", "B"], "2026-08-17")
    assert "A" not in scores and scores["B"] == 75.0
    # radar/degrade.py's own docstring is about exactly this regression: a fail-soft
    # path that goes silent. Deleting the warn() call must not leave the suite green.
    assert any(e["what"] == "wikimedia" for e in degrade.events())


def test_thin_baseline_is_absent_not_zero(monkeypatch):
    """None from spike_score must not become 0.0 -- a real zero says 'collapsed
    attention', absence says 'no signal'. composite.py renormalizes around absence."""
    monkeypatch.setattr(pv, "_get_series", lambda *a, **k: [2] * 28 + [12])
    scores, raw, _failed = pv.fetch_attention({"T": "Title"}, ["T"], "2026-08-17")
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
    makes _get_series return MISS, so the ticker ends up absent from scores rather than
    silently wrong — and MISS, not None, because Wikimedia answered: the refusal is ours,
    and charging it to the breaker would drop attention for every ticker after it."""
    fixture = json.loads(Path("tests/fixtures/pageviews_tsla.json").read_text())
    fixture["items"][-1]["timestamp"] = "2026081500"  # requested end is 2026-08-16 (D-2)
    class Resp:
        status_code = 200
        def json(self):
            return fixture
    monkeypatch.setattr(pv.requests, "get", lambda *a, **k: Resp())

    assert pv._get_series("Tesla, Inc.", "20260712", "20260816") == pv.MISS

    scores, raw, failed = pv.fetch_attention({"TSLA": "Tesla, Inc."}, ["TSLA"], "2026-08-17")
    assert "TSLA" not in scores
    assert "TSLA" not in raw
    assert any(e["what"] == "wikimedia" for e in degrade.events())
    assert failed == 0, "a short window is Wikimedia ANSWERING — not an outage to report"


def test_a_wikimedia_outage_trips_a_breaker_instead_of_stalling_the_run(monkeypatch):
    """No breaker meant a hung Wikimedia cost 15 tickers x timeout=20s ~= 5 minutes of
    serial stall inside the job that gates the 6:17 AM publish. This project already has
    the precedent and the pattern: radar/run.py:133-140 breaks cboe after 3 consecutive
    failures, and config.yaml records why ("worst case was 2x30s x10 tickers ~ 10.5 min
    serial stall on outage").

    Three consecutive failures is a dead source, not a coincidence — keep going and you
    are just paying the timeout again for the same answer."""
    calls = []
    monkeypatch.setattr(pv, "_get_series", lambda *a, **k: calls.append(a[0]))  # -> None
    titles = {f"T{i}": f"Title {i}" for i in range(15)}
    scores, raw, failed = pv.fetch_attention(titles, list(titles), "2026-08-17", sleep_s=0)

    assert len(calls) == 3, f"breaker never tripped — made {len(calls)} calls into a dead source"
    assert (scores, raw) == ({}, {})
    assert failed == 3, "three dead requests is the outage the LED must report"
    assert any("skipping remaining" in e["reason"] for e in degrade.events()), \
        "a tripped breaker must say so — a silent early exit looks like a covered board"


def test_the_breaker_counts_CONSECUTIVE_failures_not_total(monkeypatch):
    """The distinction that makes the breaker safe: scattered TRANSPORT failures — the
    one flaky request, the one timeout — must never stop the walk. Only an unbroken run
    of three does. Here every other ticker fails, so the counter keeps resetting and all
    15 are attempted. (An ordinary miss does not even start the run: see the 404 and
    stale-tail tests at the end of this file.)"""
    calls = []
    good = [10] * 28 + [40]

    def flaky(title, start, end):
        calls.append(title)
        return None if len(calls) % 2 else good

    monkeypatch.setattr(pv, "_get_series", flaky)
    titles = {f"T{i}": f"Title {i}" for i in range(15)}
    scores, raw, _failed = pv.fetch_attention(titles, list(titles), "2026-08-17", sleep_s=0)

    assert len(calls) == 15, "scattered failures must not trip the breaker"
    assert len(scores) == 7 and len(raw) == 7


def test_a_transient_429_is_retried_rather_than_charged_to_the_breaker(monkeypatch):
    """This was the only new transport with no retry, and the omission is not cosmetic:
    the walk is SERIAL across every board ticker and shares one 3-strike breaker, so a
    rate limiter — which by construction hands out 429s CONSECUTIVELY — trips it in
    three tickers and drops attention for the whole rest of the board. Its three
    siblings (cramer._get_json, tickermap._get_json, short_interest._get_json /
    _post_json) all retry 429/500/502/503 with exponential backoff; this one now
    matches, and the breaker above it is untouched."""
    fixture = json.loads(Path("tests/fixtures/pageviews_tsla.json").read_text())
    codes = [429, 200]
    calls = []

    class Resp:
        def __init__(self, code):
            self.status_code = code

        def json(self):
            return fixture

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        return Resp(codes[len(calls) - 1])

    monkeypatch.setattr(pv.requests, "get", fake_get)
    monkeypatch.setattr(pv.time, "sleep", lambda *_a, **_k: None)   # no real backoff in tests
    series = pv._get_series("Tesla, Inc.", "20260712", "20260816")

    assert len(calls) == 2, "a 429 must be retried, not treated as a dead source"
    assert series is not None and len(series) == 29


def test_a_404_is_an_ordinary_miss_and_is_not_retried(monkeypatch):
    """The other half of the retry contract, and the reason it is a status-code
    WHITELIST rather than `!= 200`: an unmapped or renamed article answers 404 forever,
    and retrying it doubles the cost of every miss on a healthy walk."""
    calls = []

    class Resp:
        status_code = 404

        def json(self):
            return {}

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        return Resp()

    monkeypatch.setattr(pv.requests, "get", fake_get)
    monkeypatch.setattr(pv.time, "sleep", lambda *_a, **_k: pytest.fail("404 must not back off"))
    assert pv._get_series("Tesla, Inc.", "20260712", "20260816") == pv.MISS, \
        "MISS, not None: None means the transport failed, and the breaker counts those"
    assert len(calls) == 1, "a 404 is a miss, not an outage"


def test_a_stale_tail_is_a_refusal_and_is_not_retried(monkeypatch):
    """The fail-closed tail check sits INSIDE the retry loop, so it must return rather
    than continue: Wikimedia not having published D-1 yet is a fact about the data, and
    a second identical request buys the same short window at twice the price."""
    fixture = json.loads(Path("tests/fixtures/pageviews_tsla.json").read_text())
    fixture["items"][-1]["timestamp"] = "2026081500"
    calls = []

    class Resp:
        status_code = 200

        def json(self):
            return fixture

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        return Resp()

    monkeypatch.setattr(pv.requests, "get", fake_get)
    assert pv._get_series("Tesla, Inc.", "20260712", "20260816") == pv.MISS, \
        "MISS, not None: a refusal is a fact about the data, not about the transport"
    assert len(calls) == 1, "a stale tail is a refusal, not a transient failure"


def _resp(code, body):
    class Resp:
        status_code = code

        def json(self):
            return body
    return Resp()


def _stale(fixture):
    """A copy of the fixture whose freshest day is D-2, i.e. the requested `end` is not
    the tail — exactly what Wikimedia serves when it has not published D-1 yet."""
    doc = json.loads(json.dumps(fixture))
    doc["items"][-1]["timestamp"] = "2026081500"
    return doc


def test_three_consecutive_404s_do_not_trip_the_breaker(monkeypatch):
    """A 404 is Wikimedia ANSWERING — this article does not exist. Three names in a row
    with no article is an ordinary Tuesday on a meme-stock board, not an outage, and
    `fetch_attention`'s own docstring already promised it ("a name with no article or a
    stale redirect is ordinary and must not stop a healthy walk"). Charging misses to
    the breaker silently drops attention for every ticker AFTER the third unmapped name.

    Driven through the real transport, not a `_get_series` stub: the whole point is that
    the transport now tells the caller WHICH kind of nothing it got back."""
    fixture = json.loads(Path("tests/fixtures/pageviews_tsla.json").read_text())
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        return _resp(404, {}) if len(calls) <= 3 else _resp(200, fixture)

    monkeypatch.setattr(pv.requests, "get", fake_get)
    titles = {f"T{i}": f"Title {i}" for i in range(6)}
    scores, raw, _failed = pv.fetch_attention(titles, list(titles), "2026-08-17", sleep_s=0)

    assert len(calls) == 6, f"walk stopped after {len(calls)} — 404s tripped the breaker"
    assert len(raw) == 3, "the three real articles must still be measured"
    assert not any("skipping remaining" in e["reason"] for e in degrade.events()), \
        "an ordinary miss must never read as a tripped breaker"


def test_three_consecutive_stale_tail_refusals_do_not_trip_the_breaker(monkeypatch):
    """docs/HANDOFF.md records that Wikimedia's D-1 availability at the 10:17 UTC board
    time is INFERRED from dump timestamps, never observed on the AQS API. If D-1 is not
    published when the job runs, EVERY ticker refuses on a stale tail — so counting a
    refusal as a failure makes the breaker fire after three and drops attention for the
    whole board, while the LED reports an outage that did not happen."""
    fixture = json.loads(Path("tests/fixtures/pageviews_tsla.json").read_text())
    stale = _stale(fixture)
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        return _resp(200, stale if len(calls) <= 3 else fixture)

    monkeypatch.setattr(pv.requests, "get", fake_get)
    titles = {f"T{i}": f"Title {i}" for i in range(6)}
    scores, raw, _failed = pv.fetch_attention(titles, list(titles), "2026-08-17", sleep_s=0)

    assert len(calls) == 6, f"walk stopped after {len(calls)} — refusals tripped the breaker"
    assert len(raw) == 3, "the three fresh-tailed articles must still be measured"
    assert not any("skipping remaining" in e["reason"] for e in degrade.events()), \
        "a refusal is a fact about the DATA, not about the transport"


def test_only_transport_failures_are_reported_as_an_outage(monkeypatch):
    """The count the wikimedia LED keys on. A board of nothing but 404s is a healthy
    Wikimedia answering every request, and must report ZERO transport failures — that is
    what stops radar/run.py lighting the LED red on a board of unmapped names."""
    monkeypatch.setattr(pv.requests, "get",
                        lambda url, headers=None, timeout=None: _resp(404, {}))
    titles = {f"T{i}": f"Title {i}" for i in range(4)}
    _s, _r, failed = pv.fetch_attention(titles, list(titles), "2026-08-17", sleep_s=0)
    assert failed == 0, "a 404 is an answer, not an outage"

    monkeypatch.setattr(pv.requests, "get",
                        lambda url, headers=None, timeout=None: _resp(418, {}))
    _s, _r, failed = pv.fetch_attention(titles, list(titles), "2026-08-17", sleep_s=0)
    assert failed == pv.MAX_CONSECUTIVE_FAILURES, \
        "a non-404 refusal from the transport IS an outage and must reach the LED"
