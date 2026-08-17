"""Scheme allowlist for feed-supplied links.

Alert URLs come from feeds we do not control — the Truth Social RSS `<link>` and the
third-party congress-trades JSON `doc_url` — and land in an `href` on both the public
dashboard and the alert emails. Jinja autoescaping stops tag breakout but NOT a
`javascript:` scheme, so every feed URL is filtered through `safe_url` first.
"""
import pytest

from radar.urls import safe_url


@pytest.mark.parametrize("url", [
    "https://www.sec.gov/Archives/edgar/data/1045810/nvda-20260817.htm",
    "http://example.com/filing?a=1&b=2",
    "HTTPS://WWW.SEC.GOV/x",                 # scheme match is case-insensitive
    "https://www.trumpstruth.org/statuses/40890",
])
def test_safe_url_keeps_http_and_https(url):
    assert safe_url(url) == url


@pytest.mark.parametrize("url", [
    "javascript:alert(1)",
    "JavaScript:alert(1)",
    "  javascript:alert(1)  ",               # leading/trailing space
    "java\tscript:alert(1)",                 # urlsplit strips ASCII tab/CR/LF
    "java\nscript:alert(1)",
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
    "//evil.example.com/x",                  # protocol-relative: no scheme of its own
    "/relative/path",
    "",
    "   ",
])
def test_safe_url_drops_every_other_scheme(url):
    assert safe_url(url) == ""


@pytest.mark.parametrize("value", [None, 12, 1.5, {"u": "https://x"}, ["https://x"]])
def test_safe_url_non_string_is_dropped(value):
    assert safe_url(value) == ""


def test_safe_url_malformed_never_raises():
    # urlsplit raises ValueError on an unmatched IPv6 bracket — a feed must not crash the run.
    assert safe_url("http://[oops") == ""


# ---- the two places a feed URL reaches an href ----

from radar.render import render_html

_MIN = dict(meta=dict(date="x", edition_no=1, corpus_count="0", signals_tracked=0,
                      biggest_breakout="—", most_bullish="—"),
            today_read=dict(lead="No signals today.", bullets=[]),
            board=[], movers=[], listings=[], themes=["All"], cooling=[], trend="")


def _alert(url):
    return dict(tag="⚠ Congress Buy", tickers="$NVDA", body="a purchase", meta="2026-08-17",
                style="trump", link_text="View filing ↗", theme_attr="Trump", url=url)


def test_dashboard_drops_javascript_alert_link():
    html = render_html(alerts=[_alert("javascript:alert(1)")], **_MIN)
    assert "javascript:" not in html.lower()
    assert "View filing" not in html          # whole link dropped, not just the scheme


def test_dashboard_keeps_https_alert_link():
    html = render_html(alerts=[_alert("https://www.sec.gov/x.htm")], **_MIN)
    assert 'href="https://www.sec.gov/x.htm"' in html
    assert "View filing" in html


def _monitor_alert(url):
    return dict(label="Congress buy", tickers=["NVDA"], summary="Pelosi bought NVDA",
                published="2026-08-17T00:00:00Z", link_text="View filing ↗", url=url)


def test_monitor_email_drops_javascript_url():
    from radar.email_report import build_monitor_alert_email
    html = build_monitor_alert_email(_monitor_alert("javascript:alert(1)"))
    assert "javascript:" not in html.lower()


def test_monitor_email_keeps_https_url():
    from radar.email_report import build_monitor_alert_email
    html = build_monitor_alert_email(_monitor_alert("https://www.sec.gov/x.htm"))
    assert 'href="https://www.sec.gov/x.htm"' in html


def test_trump_email_drops_javascript_url():
    from radar.email_report import build_trump_alert_email
    html = build_trump_alert_email(dict(tickers=["DJT"], post="a post",
                                        published="2026-08-17T00:00:00Z",
                                        url="javascript:alert(1)"))
    assert "javascript:" not in html.lower()


def test_dashboard_button_still_renders_own_https_links():
    # regression guard: the sanitizer must not break the footer's own dashboard button
    from radar.email_report import build_email_html, DASHBOARD_URL
    html = build_email_html("Aug 17 2026", [])
    assert DASHBOARD_URL in html
