import datetime as dt
import pathlib

from radar import trump
from radar.universe import Universe

FIX = pathlib.Path("tests/fixtures/trumpstruth.xml").read_text()
WATCH = trump.load_watch_map("data/trump_watch.yaml")


def U():
    return Universe(symbols={"TSLA", "BTC", "DJT", "AAPL"}, stopwords={"A", "I", "GREAT"})


def test_parse_rss_items():
    posts = trump.parse_rss(FIX)
    assert len(posts) == 4
    p = posts[0]
    assert p.id.endswith("40001") and "$TSLA" in p.text and p.published.startswith("2026-06-02")


def test_parse_rss_malformed_returns_empty():
    assert trump.parse_rss("<<not xml>>") == []
    assert trump.parse_rss("") == []


def test_detect_cashtag():
    assert trump.detect_tickers("$TSLA is HUGE", U(), WATCH) == {"TSLA"}


def test_detect_company_name():
    assert "BTC" in trump.detect_tickers("Bitcoin is the future", U(), WATCH)


def test_detect_truth_social_djt():
    assert "DJT" in trump.detect_tickers("Truth Social is doing great", U(), WATCH)


def test_detect_none_on_plain_prose():
    assert trump.detect_tickers("A GREAT day for our Country", U(), WATCH) == set()


def test_find_new_alerts_and_dedup():
    posts = trump.parse_rss(FIX)
    alerts, seen = trump.find_new_alerts(posts, [], U(), WATCH)
    tks = {t for a in alerts for t in a["tickers"]}
    assert {"TSLA", "BTC", "DJT"} <= tks
    assert len(seen) == 4                               # every post evaluated (dedup cursor)
    alerts2, _ = trump.find_new_alerts(posts, seen, U(), WATCH)
    assert alerts2 == []                                # already seen -> no re-alert


def test_alert_freshness():
    now = dt.datetime(2026, 6, 2, 13, 0, tzinfo=dt.timezone.utc).timestamp()
    assert trump.alert_is_fresh({"detected_at": "2026-06-02T12:00:00Z"}, now, 48) is True
    assert trump.alert_is_fresh({"detected_at": "2026-05-01T00:00:00Z"}, now, 48) is False
    assert trump.alert_is_fresh({}, now) is False


def test_build_write_load_alert(tmp_path):
    alerts, _ = trump.find_new_alerts(trump.parse_rss(FIX), [], U(), WATCH)
    a = trump.build_alert(alerts, "2026-06-02T12:30:00Z")
    assert a["detected_at"] == "2026-06-02T12:30:00Z" and a["tickers"]
    p = tmp_path / "alert.json"
    trump.write_alert_json(p, a)
    assert trump.load_alert(p)["tickers"] == a["tickers"]


def test_trump_email_escapes_post():
    from radar.email_report import build_trump_alert_email
    html = build_trump_alert_email(dict(tickers=["TSLA"], post="<script>alert(1)</script> buy",
                                        url="http://x", published="2026-06-02T12:00:00Z"))
    assert "<script>alert(1)</script>" not in html      # escaped
    assert "&lt;script&gt;" in html and "$TSLA" in html


def test_render_alert_card_and_escape():
    from radar.run import _build_context
    from radar.render import render_html
    alert = dict(tickers="$TSLA", post="<script>x</script> Tesla is great", url="http://t", when="2026-06-02")
    html = render_html(**_build_context([], [], "2026-06-02", 0, alert=alert))
    assert "Trump Alert" in html and "$TSLA" in html
    assert "<script>x</script>" not in html             # post text escaped server-side
    html2 = render_html(**_build_context([], [], "2026-06-02", 0))
    assert "Trump Alert" not in html2                   # no alert -> no card


def test_monitor_writes_alert_then_dedups(tmp_path, monkeypatch):
    import radar.monitor as mon
    monkeypatch.setattr(trump, "fetch_rss", lambda *a, **k: trump.parse_rss(FIX))
    monkeypatch.setattr(mon, "ALERT_PATH", str(tmp_path / "alert.json"))
    monkeypatch.setattr(mon, "SEEN_PATH", str(tmp_path / "seen.json"))
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert mon.main([]) == 0
    a = trump.load_alert(str(tmp_path / "alert.json"))
    assert a and a["tickers"]                           # real universe resolves TSLA/BTC/DJT
    assert mon.main([]) == 0                             # all seen -> no crash, no new alert
