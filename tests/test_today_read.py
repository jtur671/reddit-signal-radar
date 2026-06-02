from radar.run import _today_read, _build_context, _read_bullet_why, _why_matters
from radar.sentiment import _parse_read
from radar.render import render_html
from radar.models import Signal
from radar.themes import Themes


def _themes():
    raw = {"ai_compute": {"label": "AI Compute", "seeds": ["IREN"]},
           "crypto": {"label": "Crypto", "seeds": ["BTC"]},
           "oil": {"label": "Oil", "seeds": ["XOM"]}}
    return Themes(raw)


def _sig(ticker, score, themes, mentions=100, vel=None, state="new"):
    s = Signal(ticker=ticker, score=score, mentions=mentions)
    s.themes = themes
    s.vel_24h = vel
    s.state = state
    s.name = ticker
    s.about_extract = ""
    s.about_desc = ""
    return s


# --- DeepSeek output parsing -------------------------------------------------

def test_parse_read_extracts_lead_and_bullets():
    text = ("LEAD: AI compute names lead today, with IREN the standout.\n"
            "IREN: datacenter buildout chatter accelerating\n"
            "> BTC — riding the broader risk-on bid.\n")
    out = _parse_read(text, {"IREN", "BTC"})
    assert out["lead"].startswith("AI compute names lead")
    assert {b["ticker"] for b in out["bullets"]} == {"IREN", "BTC"}
    assert out["bullets"][0]["why"] == "datacenter buildout chatter accelerating"


def test_parse_read_ignores_unknown_tickers_and_dupes():
    text = "LEAD: x\nIREN: a\nIREN: dup\nFAKE: nope\n"
    out = _parse_read(text, {"IREN"})
    assert [b["ticker"] for b in out["bullets"]] == ["IREN"]


# --- Deterministic fallback (no DeepSeek key) --------------------------------

def test_today_read_falls_back_without_deepseek(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    board = [_sig("IREN", 50, ["AI Compute"], vel=2.4, state="hot"),
             _sig("BTC", 30, ["Crypto"], vel=0.7, state="cooling")]
    read = _today_read(board, _themes())
    assert read["lead"]                                   # never blank
    assert {b["ticker"] for b in read["bullets"]} == {"IREN", "BTC"}
    # no raw mention counts leak into the read
    joined = read["lead"] + " ".join(b["why"] for b in read["bullets"])
    assert "100 mentions" not in joined and "mentions today" not in joined


def test_fallback_bullet_has_no_mention_counts():
    s = _sig("IREN", 50, ["AI Compute"], vel=2.4, state="hot")
    why = _read_bullet_why(s)
    assert "mention" not in why.lower() and "100" not in why  # qualitative only, no counts


# --- Why It Matters ----------------------------------------------------------

def test_why_matters_fallback_is_actionable_and_number_free(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    board = [_sig("IREN", 50, ["AI Compute"], vel=2.4, state="hot"),
             _sig("BTC", 30, ["Crypto"], vel=1.3, state="hot")]
    take = _why_matters(board, {"lead": "AI compute leads."})
    assert take and "IREN" in take
    assert "buy signal" in take.lower()                  # grounded caveat present
    assert "mention" not in take.lower()


def test_why_matters_handles_empty_board(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert _why_matters([], {}).strip()                  # never blank


def test_why_matters_renders_as_section(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    sig = _sig("BTC", 40, ["Crypto"], vel=3.0, state="hot")
    ctx = _build_context([sig], [sig], "2026-06-02", 1000,
                         today_read=_today_read([sig], _themes()),
                         why_matters=_why_matters([sig], {}))
    html = render_html(**ctx)
    assert "Why It Matters" in html


# --- Render integration ------------------------------------------------------

def test_today_read_renders_and_is_never_blank(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    sig = _sig("BTC", 40, ["Crypto"], vel=3.0, state="hot")
    read = _today_read([sig], _themes())
    ctx = _build_context([sig], [sig], "2026-06-02", 1000, today_read=read)
    html = render_html(**ctx)
    assert "BTC" in html
    assert "Today's Read" in html
    assert "(100 mentions)" not in html                   # mechanical counts are gone
