import json

from radar.sentiment import _parse_buys, recommend_buys
from radar.run import _build_context
from radar.render import render_html
from radar.models import Signal


# --- parsing -----------------------------------------------------------------

def test_parse_buys_validates_dedupes_and_caps():
    text = json.dumps({"picks": [
        {"ticker": "$VRT", "thesis": "AI data-center demand", "risk": "low volume", "conviction": "High"},
        {"ticker": "FAKE", "thesis": "x", "risk": "y", "conviction": "low"},      # not on board -> dropped
        {"ticker": "VRT", "thesis": "dupe", "risk": "z", "conviction": "low"},     # dupe -> dropped
        {"ticker": "OKLO", "thesis": "nuclear AI power", "risk": "speculative", "conviction": "medium"},
        {"ticker": "CEG", "thesis": "a", "risk": "b", "conviction": "low"},
    ]})
    out = _parse_buys(text, {"VRT", "OKLO", "CEG"}, max_picks=3)
    assert [p["ticker"] for p in out] == ["VRT", "OKLO", "CEG"]
    assert out[0]["conviction"] == "high"          # normalized lowercase, valid value
    assert out[0]["thesis"] == "AI data-center demand"


def test_parse_buys_bad_json_is_empty():
    assert _parse_buys("not json", {"VRT"}) == []
    assert _parse_buys(json.dumps({"nope": 1}), {"VRT"}) == []


def test_parse_buys_drops_bad_conviction():
    text = json.dumps({"picks": [{"ticker": "VRT", "thesis": "t", "risk": "r", "conviction": "strong buy"}]})
    assert _parse_buys(text, {"VRT"})[0]["conviction"] == ""   # only high/medium/low kept


# --- fail-closed -------------------------------------------------------------

def test_recommend_buys_fails_closed_without_deepseek(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    cands = [dict(ticker="VRT", name="Vertiv", theme="AI", mentions=21, vel="21×", state="new", summary="x")]
    assert recommend_buys(cands) == []             # never fabricate buy ideas


# --- render ------------------------------------------------------------------

def _sig(t):
    s = Signal(ticker=t, mentions=10); s.themes = ["AI"]; s.vel_24h = 2.0; s.name = t; return s


def test_early_plays_card_renders_with_caveat():
    plays = [dict(ticker="VRT", name="Vertiv", vel24="21×", conviction="high",
                  thesis="AI data-center demand catalyst", risk="thin volume")]
    html = render_html(**_build_context([_sig("VRT")], [_sig("VRT")], "2026-06-02", 100,
                                        early_plays=plays))
    assert "DeepSeek Early Plays" in html
    assert "$VRT" in html and "AI data-center demand catalyst" in html
    assert "Not financial advice" in html
    assert 'class="play" data-ticker="VRT"' in html     # click-through to detail modal


def test_no_early_plays_no_card():
    html = render_html(**_build_context([_sig("VRT")], [_sig("VRT")], "2026-06-02", 100))
    assert "DeepSeek Early Plays" not in html


def test_early_plays_thesis_is_escaped():
    plays = [dict(ticker="VRT", name="Vertiv", vel24="", conviction="",
                  thesis="<script>alert(1)</script>", risk="")]
    html = render_html(**_build_context([_sig("VRT")], [_sig("VRT")], "2026-06-02", 100,
                                        early_plays=plays))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
