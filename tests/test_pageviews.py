import json
import math
from datetime import date
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
                        lambda url, headers=None, timeout=None: _resp(403, {}))
    _s, _r, failed = pv.fetch_attention(titles, list(titles), "2026-08-17", sleep_s=0)
    assert failed == pv.MAX_CONSECUTIVE_FAILURES, \
        "access refused IS an outage and must reach the LED"
    # 403, not the 418 this test used to send. The rest of the 4xx range is now a MISS,
    # because 400/404/414 are Wikimedia answering about OUR input (see
    # test_our_own_bad_title_is_not_counted_as_a_wikimedia_outage) -- and 418 was only
    # ever a stand-in for "some other refusal". 403 is the real one and the one this
    # module's docstring already named: measured live 2026-08-18, an empty User-Agent
    # gets 403 where a real one gets 200, so it means our ACCESS is gone, board-wide,
    # which is exactly what the LED exists to say.


# ======================================================================================
# Chaos-gate and polarity-gate findings, 2026-08-18. Every one reproduced against the
# real module before the fix; the mutation each test kills is named in its docstring.
# ======================================================================================


def test_parse_series_drops_non_finite_view_counts_instead_of_raising():
    """`json.loads` accepts `Infinity`, `NaN` and `1e309` by default — verified in this
    test, and simplejson is not installed, so `requests.Response.json` IS stdlib json.
    So a 200 body can hand this function a float `inf`, and `int(inf)` raises
    OverflowError — an ArithmeticError, caught by NEITHER this function's except tuple
    NOR `_get_series`'. The docstring promises "Pure, never raises"; this is what makes
    that promise true."""
    body = json.loads('{"items": [{"timestamp": "2026081600", "views": 1e309},'
                      ' {"timestamp": "2026081500", "views": Infinity},'
                      ' {"timestamp": "2026081400", "views": NaN},'
                      ' {"timestamp": "2026081300", "views": -5},'
                      ' {"timestamp": "2026081200", "views": 12}]}')
    assert math.isinf(body["items"][0]["views"]), "stdlib json really does yield inf"
    assert pv.parse_series(body) == [("2026081200", 12)]


def test_a_non_finite_view_count_is_a_miss_not_an_escaping_overflow(monkeypatch):
    """The same body one layer up. `_get_series` catches (RequestException, ValueError)
    and `fetch_attention` wraps nothing, so the OverflowError escaped both and killed
    the 6:17 job outright — on a 200 response, from the source we treat as healthy."""
    body = json.loads('{"items": [{"timestamp": "2026081600", "views": 1e309}]}')
    monkeypatch.setattr(pv.requests, "get",
                        lambda url, headers=None, timeout=None: _resp(200, body))
    assert pv._get_series("Tesla, Inc.", "20260712", "20260816") == pv.MISS

    scores, raw, failed = pv.fetch_attention({"T": "Title"}, ["T"], "2026-08-17", sleep_s=0)
    assert (scores, raw, failed) == ({}, {}, 0), \
        "a garbage body is a miss about one name, not an outage"


def test_an_absurd_integer_never_reaches_the_arithmetic():
    """A 400-digit integer passes `int()` cleanly and only detonates downstream:
    `statistics.median` averages the two middle values of the 28-element prior window and
    `current / baseline` is a float division — both raise "OverflowError: integer
    division result too large for a float", uncaught, straight out of `fetch_attention`.
    Refused at the parse boundary so it cannot reach `spike_score` at all, and refused
    again inside `spike_score` for callers that hand it a list directly."""
    huge = 10 ** 400
    assert pv.parse_series({"items": [{"timestamp": "2026081600", "views": huge}]}) == []
    assert pv.spike_score(_flat(28, 100) + [huge]) is None
    assert pv.spike_score(_flat(28, huge) + [100]) is None


def test_a_non_string_title_is_a_miss_not_an_AttributeError(monkeypatch):
    """`title.replace(" ", "_")` sat OUTSIDE the retry try, so a non-string title raised
    straight out of `fetch_attention`. Reachable: run.py builds pv_titles preferring the
    cached canonical title from data/about.json, which rides the orphan data branch — so
    the TYPE of a title is only as good as yesterday's JSON.

    A malformed title is OUR input, so the answer is MISS. It must not become a REQUEST
    either: `str(123)` would cheerfully fetch the article "123", which exists, and
    publish a well-formed, entirely fictitious attention score — the exact failure this
    module's own docstring is written against."""
    calls = []
    monkeypatch.setattr(pv.requests, "get",
                        lambda url, headers=None, timeout=None: calls.append(url))
    for bad in (123, None, ["Tesla"], b"Tesla", "", "   "):
        assert pv._get_series(bad, "20260712", "20260816") == pv.MISS, f"{bad!r}"
    assert calls == [], "a malformed title must never reach Wikimedia"

    scores, raw, failed = pv.fetch_attention({"A": 123}, ["A"], "2026-08-17", sleep_s=0)
    assert (scores, raw, failed) == ({}, {}, 0)


def test_our_own_bad_title_is_not_counted_as_a_wikimedia_outage(monkeypatch):
    """400 (malformed/over-long title) and 414 (URI too long) are Wikimedia ANSWERING,
    about OUR input — the same class of fact as a 404, and the opposite of an outage.
    Returning None for them charged the breaker: measured, 15 tickers all answering 400
    stopped the walk at ticker three, dropped attention for the remaining 12 and lit
    `wikimedia: down` while Wikimedia answered every single request. This is the exact
    mistake the MISS sentinel was introduced to fix, one status class short."""
    for code in (400, 414):
        degrade.reset()
        calls = []

        def fake_get(url, headers=None, timeout=None):
            calls.append(url)
            return _resp(code, {})

        monkeypatch.setattr(pv.requests, "get", fake_get)
        titles = {f"T{i}": f"Title {i}" for i in range(15)}
        scores, raw, failed = pv.fetch_attention(titles, list(titles), "2026-08-17",
                                                 sleep_s=0)
        assert len(calls) == 15, f"{code} tripped the breaker after {len(calls)} tickers"
        assert (scores, raw) == ({}, {})
        assert failed == 0, f"{code} is an answer about our input, not an outage"
        assert not any("skipping remaining" in e["reason"] for e in degrade.events()), \
            f"{code} must not read as a tripped breaker"


def test_nan_or_infinity_never_scores_maximum_attention():
    """Garbage in, MAXIMUM-confidence signal out — the worst shape a bug can take here.
    `nan < min_baseline` is False, so the thin-baseline guard waved it through, and
    `min(2.0, nan)` returns 2.0 (NaN loses every comparison), so the clamp resolved to
    the TOP: 100.0, the strongest attention score on the board, from a series that means
    nothing. The log2(0) guard was incomplete too — an infinite baseline gives
    ratio 0.0 -> math.log2(0.0) -> ValueError: math domain error, without `current`
    ever being 0."""
    nan, inf = float("nan"), float("inf")
    assert pv.spike_score(_flat(28, 100) + [nan]) is None
    assert pv.spike_score(_flat(28, nan) + [200]) is None
    assert pv.spike_score(_flat(28, 100) + [inf]) is None
    assert pv.spike_score(_flat(28, inf) + [200]) is None
    assert pv.spike_score(_flat(28, 100) + [-5]) is None


def test_min_days_above_the_baseline_window_is_not_a_silent_dead_zone():
    """`prior` is `series[-(BASELINE_DAYS + 1):-1]` — structurally capped at 28 elements
    — so any min_days above 28 can NEVER be satisfied: every ticker scores None forever
    and nothing anywhere says why. FETCH_DAYS (35) sits one identifier away as a
    plausible-looking value to pass.

    Clamped rather than asserted at import, because min_days is a per-CALL parameter that
    import time cannot see; and clamped rather than raised, because raising would escape
    `fetch_attention`'s fail-soft loop and take the whole walk down with it."""
    series = _flat(28, 100) + [200]
    assert pv.spike_score(series, min_days=pv.FETCH_DAYS) == 75.0
    assert pv.spike_score(series, min_days=29) == 75.0
    assert pv.spike_score(_flat(20, 100) + [200], min_days=pv.FETCH_DAYS) is None, \
        "the clamp must not also disable the genuine too-few-days guard"


def test_the_fetch_window_ends_at_D_minus_1_and_spans_FETCH_DAYS(monkeypatch):
    """The window `fetch_attention` computes was pinned by NOTHING: every other test
    either stubs `_get_series` away or passes literal date strings, so swapping start and
    end, shrinking the span to 4 days, or dropping FETCH_DAYS to 3 all survived the whole
    suite. Measured against the live API on 2026-08-18: a reversed window returns HTTP
    400 (it is NOT order-agnostic) while the same window in order returns 200 — so a
    flipped subtraction is board-wide attention loss, silently."""
    seen = {}

    def fake(title, start, end):
        seen["start"], seen["end"] = start, end
        return pv.MISS

    monkeypatch.setattr(pv, "_get_series", fake)
    pv.fetch_attention({"T": "Title"}, ["T"], "2026-08-17", sleep_s=0)

    assert seen["end"] == "20260816", "the window ends at D-1, never at the run day"
    assert seen["start"] == "20260712"
    assert seen["start"] < seen["end"], "start after end is an HTTP 400 from Wikimedia"
    span = date.fromisoformat(seen["end"]) - date.fromisoformat(seen["start"])
    assert span.days == pv.FETCH_DAYS, "a shrunk window silently starves every baseline"


def test_the_window_reaches_the_url_as_start_then_end(monkeypatch):
    """The other half of the pin, one layer down: the AQS path is `/daily/{start}/{end}`,
    and swapping the two in the template is invisible to every test that stubs
    `_get_series` — including the one above."""
    fixture = json.loads(Path("tests/fixtures/pageviews_tsla.json").read_text())
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        return _resp(200, fixture)

    monkeypatch.setattr(pv.requests, "get", fake_get)
    pv._get_series("Tesla, Inc.", "20260712", "20260816")
    assert captured["url"].endswith("/daily/20260712/20260816")


def test_a_zero_baseline_is_refused_rather_than_divided_by():
    """The thin-baseline guard is `baseline < min_baseline`, so a caller passing
    min_baseline=0 — the natural way to say "score everything, I'll filter downstream" —
    waved a zero median straight into `current / baseline`. ZeroDivisionError is not an
    ArithmeticError this module catches anywhere: it escapes fetch_attention exactly like
    the OverflowErrors above."""
    assert pv.spike_score(_flat(28, 0) + [5], min_baseline=0) is None
    # None rather than the real-zero 0.0 of test_zero_current_..., and deliberately so:
    # a zero MEDIAN means the name has no Wikipedia traffic to speak of, which is "no
    # signal" (the composite renormalizes around it), not the claim "attention collapsed".
    assert pv.spike_score(_flat(28, 0) + [0], min_baseline=0) is None


# --- the wall-clock budget ------------------------------------------------------------

class _Clock:
    """A `time` stand-in that burns SIMULATED seconds, so a ten-minute walk costs the
    suite nothing. Same rebind-the-module-global shape as conftest's _NoSleepTime (and
    for the same reason: `pv.time` IS the stdlib module, so setattr on its `sleep` would
    patch every other module's sleep too)."""

    def __init__(self):
        self.t = 0.0

    def sleep(self, s):
        self.t += s

    def monotonic(self):
        return self.t


def _timed_series(clock, pattern):
    """A `_get_series` stub that costs simulated time. `pattern` is a list of
    (outcome, seconds) cycled over the walk.

    The seconds are the module's own measured costs: a transport failure is
    2 attempts x 20s timeout + 1s + 2s of backoff = 43s; an answered request is 0.22s
    (the timing in pageviews.py's own docstring)."""
    calls = []

    def stub(title, start, end):
        outcome, cost = pattern[len(calls) % len(pattern)]
        calls.append(title)
        clock.t += cost
        return outcome

    return stub, calls


FLAP = [(None, 43.0), (None, 43.0), (pv.MISS, 0.22)]     # fail, fail, miss — forever


def test_a_flapping_source_never_trips_the_breaker_and_burns_ten_minutes(monkeypatch):
    """The hole the strike counter cannot see, measured before it was closed.

    A MISS deliberately RESETS the consecutive-failure counter — that reset is what
    makes the documented "Wikimedia has not published D-1" case survivable, so it must
    stay. The consequence is that fail/fail/miss never reaches three in a row: the
    breaker never trips, and the walk pays ~87s for every group of three names.

    This test exists to pin the COST, so the deadline below is measured against a real
    number rather than a guess. With the budget disabled, a 20-name walk in this
    pattern costs ~580s — nearly ten minutes inside the job that gates the 6:17 AM
    publish, and the whole time the strike counter reads at most two."""
    clock = _Clock()
    monkeypatch.setattr(pv, "time", clock)
    stub, calls = _timed_series(clock, FLAP)
    monkeypatch.setattr(pv, "_get_series", stub)
    titles = {f"T{i}": f"Title {i}" for i in range(20)}

    pv.fetch_attention(titles, list(titles), "2026-08-17", budget_s=0)

    assert len(calls) == 20, "the breaker must NOT stop a flapping walk — the miss resets it"
    assert clock.t > 500, f"the flap must really be expensive; measured {clock.t:.0f}s"
    assert not any("skipping remaining" in e["reason"] for e in degrade.events()), \
        "no three-in-a-row, so the strike counter never fires — that is the whole point"


def test_the_wall_clock_budget_stops_a_flapping_walk(monkeypatch):
    """The fix: a deadline beside the strike counter. The breaker measures STRIKES, this
    measures TIME, and this failure mode needs both — the pattern above defeats a strike
    counter by construction, and no strike counter can be tuned to catch it without
    breaking the miss-reset the D-1 case depends on."""
    clock = _Clock()
    monkeypatch.setattr(pv, "time", clock)
    stub, calls = _timed_series(clock, FLAP)
    monkeypatch.setattr(pv, "_get_series", stub)
    titles = {f"T{i}": f"Title {i}" for i in range(20)}

    scores, raw, failed = pv.fetch_attention(titles, list(titles), "2026-08-17", budget_s=180)

    assert len(calls) < 20, "the walk must stop early"
    assert clock.t < 180 + 43, "and stop within one in-flight request of the budget"
    assert failed == len(calls) - len(calls) // 3, "every failure still reaches the LED"
    assert any("budget" in e["reason"] for e in degrade.events()), \
        "abandoning names silently looks exactly like a covered board"
    assert any("skipping remaining" in e["reason"] for e in degrade.events())


def test_the_budget_does_not_truncate_a_healthy_walk(monkeypatch):
    """The other direction, and the one that would turn this guard into an outage of its
    own. A healthy 20-name walk costs ~0.42s per name (0.22s measured request + the 0.2s
    courtesy sleep) — about 8s all in, against a 180s default. Every name is asked and
    nothing warns."""
    clock = _Clock()
    monkeypatch.setattr(pv, "time", clock)
    good = [10] * 28 + [40]
    stub, calls = _timed_series(clock, [(good, 0.22)])
    monkeypatch.setattr(pv, "_get_series", stub)
    titles = {f"T{i}": f"Title {i}" for i in range(20)}

    scores, raw, failed = pv.fetch_attention(titles, list(titles), "2026-08-17")

    assert len(calls) == 20 and len(raw) == 20 and failed == 0
    assert clock.t < pv.WALK_BUDGET_SECONDS / 10, \
        f"a healthy walk must sit far under the budget; measured {clock.t:.1f}s"
    assert not degrade.events(), "a walk that finished has nothing to report"


def test_the_budget_never_fires_before_a_single_request_goes_out(monkeypatch):
    """A deadline that can abandon the walk before it starts would produce the LED bug
    this branch has now hit three times: zero requests, zero transport failures, and a
    green `wikimedia` on a run that asked nothing. The elapsed clock is zero at the top
    of the first iteration, so the first name is always attempted."""
    clock = _Clock()
    monkeypatch.setattr(pv, "time", clock)
    stub, calls = _timed_series(clock, FLAP)
    monkeypatch.setattr(pv, "_get_series", stub)
    titles = {f"T{i}": f"Title {i}" for i in range(20)}

    pv.fetch_attention(titles, list(titles), "2026-08-17", budget_s=0.0001)
    assert len(calls) == 1, "at least one name is always asked"


def test_a_hung_source_still_trips_the_breaker_first(monkeypatch):
    """The two guards are independent and the strike counter still wins where it should:
    a HUNG Wikimedia (every request a transport failure) is three strikes at 129s, well
    inside the budget. Adding a deadline must not have weakened the breaker."""
    clock = _Clock()
    monkeypatch.setattr(pv, "time", clock)
    stub, calls = _timed_series(clock, [(None, 43.0)])
    monkeypatch.setattr(pv, "_get_series", stub)
    titles = {f"T{i}": f"Title {i}" for i in range(20)}

    _s, _r, failed = pv.fetch_attention(titles, list(titles), "2026-08-17")
    assert len(calls) == pv.MAX_CONSECUTIVE_FAILURES and failed == 3
    assert clock.t < pv.WALK_BUDGET_SECONDS, "the breaker got there first, not the clock"
    assert not any("budget" in e["reason"] for e in degrade.events())


def test_run_py_plumbs_the_budget_from_config(monkeypatch, tmp_path):
    """The default lives in one place and the config key reaches it. A key present but
    EMPTY must fall back to the module default rather than becoming `float(None)` — the
    same `or`-not-getattr-default trap that silently disabled every ticker override."""
    import radar.run as run
    seen = {}
    monkeypatch.setattr(run.pageviews, "fetch_attention",
                        lambda titles, tickers, run_day, **k: (seen.update(k), ({}, {}, 0))[1])
    cfg_real = run.load_config

    def cfg_patched(path):
        cfg = cfg_real(path)
        cfg.pageviews.budget_seconds = None
        return cfg
    monkeypatch.setattr(run, "load_config", cfg_patched)
    # The same public fetches tests/test_run_smoke.py::_offline replaces. conftest's
    # autouse guard shuts the PRIVATE transports; `fetch_short_ratios` is a public one
    # and goes straight to cdn.finra.org — caught by the no-network gate, not guessed.
    monkeypatch.setattr(run, "fetch_mentions", lambda cfg: [])
    monkeypatch.setattr(run.tradestie, "fetch_wsb", lambda cfg: [])
    monkeypatch.setattr(run, "fetch_short_ratios", lambda cfg, run_day: ({}, ""))
    monkeypatch.setattr(run, "fetch_cramer", lambda cfg, run_day: {})
    monkeypatch.setattr(run, "option_stats", lambda ticker, cfg: None)
    monkeypatch.setattr(run.news, "headlines", lambda *a, **k: [])
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    run.main(["--dry-run", "--no-email", "--out", str(tmp_path / "out")])
    assert seen["budget_s"] == pv.WALK_BUDGET_SECONDS

    import yaml
    from pathlib import Path
    doc = yaml.safe_load(Path("config.yaml").read_text())
    assert doc["pageviews"]["budget_seconds"] == pv.WALK_BUDGET_SECONDS, \
        "config.yaml must document the same default the module ships"
