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


def test_bareword_collisions_no_longer_alert():
    """Trump's all-caps prose collides with real tickers (ICE, MASS). The bareword path is
    gone, so these never become candidates — only cashtags + named companies do."""
    u = Universe(symbols={"ICE", "MASS", "TSLA"}, stopwords=set())
    assert trump.detect_tickers("ICE and MASS deportations will be HUGE", u, WATCH) == set()
    assert trump.detect_tickers("Buy $TSLA now", u, WATCH) == {"TSLA"}


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


def test_validation_parses_yes_no():
    from radar.sentiment import _parse_validation
    out = "TSLA: YES\nICE: NO\nMASS - no\nDJT — YES"
    assert _parse_validation(out, ["TSLA", "ICE", "MASS", "DJT"]) == {"TSLA", "DJT"}


def test_validation_fails_open_without_deepseek(monkeypatch):
    from radar.sentiment import validate_trump_tickers
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    cands = [dict(ticker="TSLA", name="Tesla"), dict(ticker="ICE", name="Intercontinental")]
    assert validate_trump_tickers("anything", cands) == {"TSLA", "ICE"}   # outage never suppresses


def test_monitor_validation_drops_rejected_alerts(monkeypatch):
    """When DeepSeek rejects a candidate, the monitor drops that alert."""
    import radar.monitor as mon
    monkeypatch.setattr(mon, "validate_trump_tickers", lambda post, cands: set())
    assert mon._validate([dict(tickers=["ICE"], post="ICE raids", url="", published="")], {}) == []
    monkeypatch.setattr(mon, "validate_trump_tickers", lambda post, cands: {"TSLA"})
    kept = mon._validate([dict(tickers=["TSLA", "ICE"], post="$TSLA", url="", published="")], {})
    assert len(kept) == 1 and kept[0]["tickers"] == ["TSLA"]


def test_monitor_writes_alert_then_dedups(tmp_path, monkeypatch):
    import radar.monitor as mon
    monkeypatch.setattr(trump, "fetch_rss", lambda *a, **k: trump.parse_rss(FIX))
    monkeypatch.setattr(mon, "ALERT_PATH", str(tmp_path / "alert.json"))
    monkeypatch.setattr(mon, "SEEN_PATH", str(tmp_path / "seen.json"))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)   # validation fails open, no network
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert mon.main([]) == 0
    a = trump.load_alert(str(tmp_path / "alert.json"))
    assert a and a["tickers"]                           # real universe resolves TSLA/BTC/DJT
    assert mon.main([]) == 0                             # all seen -> no crash, no new alert
