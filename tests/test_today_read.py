from radar.run import _category_reads, _build_context
from radar.render import render_html
from radar.models import Signal
from radar.themes import Themes


def _themes():
    raw = {"ai_compute": {"label": "AI Compute", "seeds": ["IREN"]},
           "crypto": {"label": "Crypto", "seeds": ["BTC"]},
           "oil": {"label": "Oil", "seeds": ["XOM"]}}
    return Themes(raw)


def _sig(ticker, score, themes, mentions=100, vel=None):
    s = Signal(ticker=ticker, score=score, mentions=mentions)
    s.themes = themes
    s.vel_24h = vel
    return s


def test_category_read_picks_top_signal_per_theme():
    sigs = [_sig("IREN", 50, ["AI Compute"], vel=2.4), _sig("HIVE", 30, ["AI Compute"], vel=1.1)]
    reads = {r["category"]: r for r in _category_reads(sigs, _themes())}
    assert reads["AI Compute"]["ticker"] == "IREN" and not reads["AI Compute"]["quiet"]
    assert "IREN" in reads["AI Compute"]["line"] and "2.4×" in reads["AI Compute"]["line"]


def test_category_read_quiet_when_no_signal():
    reads = {r["category"]: r for r in _category_reads([], _themes())}
    assert reads["Oil"]["quiet"] and reads["Oil"]["line"].endswith("quiet")


def test_category_read_covers_all_categories_in_order():
    reads = _category_reads([_sig("BTC", 40, ["Crypto"], vel=3.0)], _themes())
    assert [r["category"] for r in reads] == ["AI Compute", "Crypto", "Oil"]


def test_today_read_never_blank_without_deepseek():
    sig = _sig("BTC", 40, ["Crypto"], vel=3.0)
    ctx = _build_context([sig], [sig], "2026-06-02", 1000,
                         category_reads=_category_reads([sig], _themes()))
    assert ctx["mood"] == ""                       # no DeepSeek summary
    html = render_html(**ctx)
    assert "Crypto — BTC" in html                  # category line present regardless
