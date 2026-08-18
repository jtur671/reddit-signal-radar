"""Wikimedia pageviews — attention from outside the forums.

The board measures Reddit. This measures whether the wider world is looking a name up,
which is the discriminator between a real story and a brigade: a brigade moves Reddit
mentions without moving Wikipedia, a genuine story moves both.

Scored as a SELF-relative spike (today vs the ticker's own trailing median), not a
board-relative percentile -- a cross-sectional rank would mostly measure market cap, and
NVDA would outrank a genuinely spiking micro-cap every day.

Titles come from radar/tickermap.py and are EXACT. An unmapped ticker gets no request:
pageviews for a wrong article are a plausible, well-formed, entirely fictitious signal.
"""
from __future__ import annotations

import math
import statistics
import time
import urllib.parse
from datetime import date, timedelta

import requests

from radar import degrade

REST = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
        "en.wikipedia/all-access/user/{title}/daily/{start}/{end}")
UA = "reddit-signal-radar/0.1 (open-source ticker signal bot)"

BASELINE_DAYS = 28
FETCH_DAYS = 35          # slack, so missing datapoints still leave a full baseline
MAX_CONSECUTIVE_FAILURES = 3   # circuit breaker; see fetch_attention

# Sentinel for "Wikimedia answered, and the answer is that there is no usable series
# here" -- a 404 (no such article) or a tail Wikimedia has not published yet. Distinct
# from None, which means the TRANSPORT failed and Wikimedia said nothing at all. The
# distinction is the breaker's whole input: a miss is an ordinary fact about one name,
# an outage is a fact about the source. Same shape as radar/options.py's "missing"
# sentinel, which the cboe loop this breaker was modelled on already reads.
MISS = "miss"

# Ceiling on a plausible daily view count. Measured against the live AQS API on
# 2026-08-18: all of en.wikipedia served 6.75e9 user pageviews in July 2026 (~2.2e8 a
# day, ALL articles), and Main_Page -- the busiest single article there is -- runs ~6.9e6
# a day. 1e12 is four orders of magnitude above the whole project's daily total, so it
# is a shape check no real name can ever reach, not a cap on anything. See _usable.
MAX_VIEWS = 10 ** 12


def _usable(views) -> bool:
    """True for a plain, finite, plausible daily view count.

    Bounded by COMPARISON rather than by math.isfinite(), deliberately: isfinite()
    converts its argument to a float first, so math.isfinite(10**400) raises
    OverflowError itself and the guard becomes the crash. A chained comparison never
    converts, and NaN loses every comparison, so this one expression rejects NaN, both
    infinities, negatives and 400-digit integers alike.

    The ceiling is what keeps the arithmetic downstream TOTAL: statistics.median averages
    the two middle values of an even-length window and `current / baseline` is a float
    division, and both raise "OverflowError: integer division result too large for a
    float" on a big enough int -- which json.loads will happily hand us, since a JSON
    number has no size limit."""
    return isinstance(views, (int, float)) and 0 <= views <= MAX_VIEWS


def spike_score(series, min_baseline: int = 10, min_days: int = 21) -> float | None:
    """0-100 from today's views against this ticker's own median. None when the signal
    would be noise: too few baseline days, a baseline too thin to be meaningful, or a
    series carrying something that is not a real view count."""
    # `prior` below is structurally capped at BASELINE_DAYS elements, so any min_days
    # above that cap can NEVER be satisfied: every ticker scores None forever and nothing
    # says why -- with FETCH_DAYS (35) sitting one identifier away as a plausible-looking
    # value to pass. Clamped rather than asserted at import, because min_days is a
    # per-CALL argument that import time cannot see; and clamped rather than raised,
    # because a raise escapes fetch_attention's fail-soft loop and takes the walk down.
    # Above the cap, "as many days as the window can hold" is the only satisfiable
    # reading of the argument.
    min_days = min(min_days, BASELINE_DAYS)
    if not series or len(series) < 2:
        return None
    current, prior = series[-1], series[-(BASELINE_DAYS + 1):-1]
    if len(prior) < min_days:
        return None
    if not _usable(current) or not all(_usable(v) for v in prior):
        # NaN is the dangerous member of this set, because it fails SILENTLY UPWARD:
        # `nan < min_baseline` is False so the thin-baseline guard passed it, and
        # `min(2.0, nan)` returns 2.0 because NaN loses every comparison, so the clamp
        # resolved to the TOP -- garbage in, 100.0 out, the strongest attention signal on
        # the board. This also subsumes the old `current < 0` check.
        return None
    baseline = statistics.median(prior)
    # `baseline <= 0` is redundant against the default min_baseline of 10 and is not:
    # a caller passing min_baseline=0 would otherwise reach `current / 0`.
    if baseline <= 0 or baseline < min_baseline:
        return None
    if current == 0:
        # A real zero: attention collapsed. That is a claim, not an absence of one --
        # None means no signal at all, which triggers the composite's renormalize-
        # around-absence path. Guarding here also keeps log2(0) from ever running.
        return 0.0
    ratio = current / baseline
    if not math.isfinite(ratio) or ratio <= 0:
        # Unreachable given the guards above, and kept because it was NOT unreachable
        # without them: an infinite baseline gives ratio 0.0 -> math.log2(0.0) ->
        # "ValueError: math domain error", with `current` never being 0.
        return None
    return round(50.0 + 25.0 * max(-2.0, min(2.0, math.log2(ratio))), 2)


def parse_series(raw) -> list[tuple[str, int]]:
    """Chronological (timestamp, views) pairs, sorted ascending by timestamp. Pure,
    never raises. Keeping the timestamp (rather than discarding it for a bare views
    list) is what lets _get_series verify the tail is actually D-1 before trusting it."""
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            ts, views = str(it["timestamp"]), int(it["views"])
        except (KeyError, TypeError, ValueError, OverflowError):
            # OverflowError is the one that is easy to miss, and it was missed: json.loads
            # accepts `Infinity`, `NaN` and `1e309` by default (stdlib json, and simplejson
            # is not installed, so this is what requests.Response.json does), so a 200 body
            # can hand us a float inf -- and int(inf) raises OverflowError, an
            # ArithmeticError, which neither this tuple nor _get_series' own
            # (RequestException, ValueError) caught. It escaped both and killed the run.
            continue
        if not _usable(views):
            # Refused HERE rather than downstream: a 400-digit integer survives int()
            # perfectly intact and only detonates inside spike_score's median and
            # division, by which point it is past every fail-soft boundary in this module.
            continue
        out.append((ts, views))
    out.sort(key=lambda pair: pair[0])
    return out


def _get_series(title: str, start: str, end: str,
                retries: int = 2, sleep_s: float = 1.0) -> list[int] | str | None:
    """One request returns the whole window (measured: 34 datapoints in 0.22s).

    Three outcomes, and the caller must be able to tell them apart:
      list[int] -- the daily views, tail verified to be `end`
      MISS      -- Wikimedia ANSWERED and there is nothing to score, or we never had a
                   question worth asking: a 4xx about OUR INPUT (400 malformed title,
                   404 no such article, 414 URI too long), a stale tail, or a title that
                   is not a usable string. Ordinary; not the breaker's business.
      None      -- the TRANSPORT failed: retries exhausted on a timeout/5xx/429, a 403
                   (access refused -- a bad or blocked UA is a real outage that hits
                   every ticker identically, not a missing article), or any other
                   non-retryable status. This is what the breaker counts.
    Collapsing the last two into a bare None is what let a board-wide stale tail -- the
    documented D-1 publication risk, see docs/HANDOFF.md -- read as a Wikimedia outage
    and trip the breaker on the third ticker.

    Retries 429/500/502/503 with exponential backoff, same shape as cramer._get_json
    and the two FINRA transports. Not decoration: this walk is SERIAL across every
    board ticker and shares one 3-strike breaker, so without a retry three transient
    429s -- which is what a rate limiter hands you, consecutively, by construction --
    trip the breaker and drop attention for the whole rest of the board. The breaker
    stays: it exists for a HUNG Wikimedia, where retrying buys the same answer twice.

    Fails closed if the freshest returned day is not `end`: Wikimedia sometimes omits
    the newest day or has not yet published it, and a silently-shifted `current` would
    still produce a well-formed score -- computed against the wrong day, with nothing
    downstream able to tell. That is a REFUSAL, not an outage, so it returns immediately
    rather than retrying -- the next attempt would return the same short window."""
    if not isinstance(title, str) or not title.strip():
        # A malformed title is a fact about OUR input, so it is a MISS. Guarded here
        # because `title.replace(...)` below sits OUTSIDE the retry try, so an
        # AttributeError there escapes fetch_attention and kills the run -- and run.py
        # builds pv_titles preferring the cached canonical title from data/about.json,
        # so a title's TYPE is only as good as yesterday's cache on the data branch.
        # Coerced with str() rather than refused, it would be worse than a crash:
        # str(123) fetches the article "123", which exists, and publishes a well-formed,
        # entirely fictitious attention score.
        return MISS
    url = REST.format(title=urllib.parse.quote(title.replace(" ", "_"), safe=""),
                      start=start, end=end)
    for attempt in range(retries):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
            if r.status_code == 200:
                pairs = parse_series(r.json())
                if not pairs or pairs[-1][0][:8] != end:
                    return MISS
                return [views for _, views in pairs]
            if r.status_code in (429, 500, 502, 503):
                time.sleep(sleep_s * (2 ** attempt)); continue
            if r.status_code == 403:
                # Access refused, not an article refused: measured live 2026-08-18, an
                # empty User-Agent gets 403 where a real one gets 200. That is a fact
                # about OUR ACCESS to the source, it hits every ticker identically, and
                # the LED must report it -- so it is carved out of the range below.
                return None
            if 400 <= r.status_code < 500:
                # Wikimedia ANSWERING, about our input: 400 malformed/over-long title,
                # 404 no such article, 414 URI too long. Ordinary and per-name. Charging
                # these to the breaker is the mistake the MISS sentinel was introduced to
                # fix, one status class short: measured, 15 tickers all answering 400
                # stopped the walk at ticker three, dropped attention for the remaining
                # 12, and lit `wikimedia: down` while Wikimedia answered every request.
                return MISS
            return None          # anything else non-retryable IS the transport failing
        except (requests.RequestException, ValueError, OverflowError):
            time.sleep(sleep_s * (2 ** attempt))
    return None


def fetch_attention(titles: dict, tickers: list, run_day: str, sleep_s: float = 0.2):
    """({ticker: 0-100}, {ticker: latest views}, transport_failures) for mapped tickers.
    Fail-soft: a ticker that errors or scores None is simply absent from the scores dict.

    The third element is the count of tickers where the TRANSPORT failed -- Wikimedia
    said nothing at all. It is what radar/run.py's wikimedia LED keys on, because that
    is the only outcome that means "the source is down": a board where every mapped
    title 404s produced no scores and no raw views, and is still a perfectly healthy
    Wikimedia answering every request.

    Breaks after MAX_CONSECUTIVE_FAILURES. This walk is serial and each request carries a
    20s timeout, so a hung Wikimedia costs 15 tickers x 20s ~= 5 minutes of stall inside
    the job that gates the daily publish -- and every one of those requests buys the same
    answer. Same breaker as radar/run.py's cboe loop, for the same measured reason. The
    counter is CONSECUTIVE, not total: a name with no article or a stale redirect is
    ordinary and must not stop a healthy walk. Only `_get_series` returning None counts;
    a MISS resets the run, because a 404 or a short window is Wikimedia ANSWERING and
    therefore positive evidence the source is up. That distinction is load-bearing:
    Wikimedia's D-1 availability at board time is inferred, never observed (see
    docs/HANDOFF.md), so a board-wide stale tail is a live scenario -- and counting
    refusals would trip the breaker on ticker three and drop attention for everyone."""
    end = date.fromisoformat(run_day) - timedelta(days=1)
    start = end - timedelta(days=FETCH_DAYS)
    s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    scores, raw_views = {}, {}
    transport_failures = misses = consecutive_failures = 0
    asked = [t for t in tickers if titles.get(t)]
    for i, ticker in enumerate(asked):
        series = _get_series(titles[ticker], s, e)
        if series is None:                      # the transport failed — breaker business
            transport_failures += 1
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                degrade.warn("wikimedia",
                             f"skipping remaining {len(asked) - i - 1} after "
                             f"{MAX_CONSECUTIVE_FAILURES} consecutive transport failures")
                break
            continue
        consecutive_failures = 0                # Wikimedia answered — the source is up
        if series == MISS or not series:        # no article, or a day not published yet
            misses += 1
            # Paced like any other answered request. It matters more than it used to:
            # a miss no longer risks tripping the breaker, so a board of unmapped names
            # now walks all 15 instead of stopping at 3, and the spec's courtesy sleep
            # is specified between REQUESTS, not between successes.
            time.sleep(sleep_s)
            continue
        raw_views[ticker] = series[-1]
        score = spike_score(series)
        if score is not None:
            scores[ticker] = score
        time.sleep(sleep_s)
    # Two warns, not one: both are breadcrumbs in health.json, but they are different
    # claims. "transport failed" is an accusation against Wikimedia; "no usable series"
    # is a statement about our own ticker->article coverage, and conflating them is what
    # made an unmapped board look like an outage.
    if transport_failures:
        degrade.warn("wikimedia", f"{transport_failures} ticker(s) failed transport")
    if misses:
        degrade.warn("wikimedia", f"{misses} ticker(s) returned no usable series "
                                  f"(no article, or {e} not published yet)")
    return scores, raw_views, transport_failures
