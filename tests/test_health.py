import json
import types

from radar import degrade
from radar.email_report import build_health_alert_email, send_health_alert
from radar.health import assess
from radar.render import write_outputs


def _sig(price=10.0, summary="a real catalyst"):
    return types.SimpleNamespace(price=price, summary=summary)


def setup_function(_):
    degrade.reset()


# --- assess ---------------------------------------------------------------

def test_clean_board_is_ok():
    h = assess([_sig(), _sig()], [], deepseek_key_present=True)
    assert h["status"] == "ok" and h["severe"] == [] and h["problems"] == []


def test_empty_board_is_severe():
    h = assess([], [], deepseek_key_present=False)
    assert h["status"] == "severe" and "board is empty" in h["severe"][0]


def test_half_prices_missing_is_severe():
    """The outage class this module exists for: prices silently blanked board-wide."""
    h = assess([_sig(price=None), _sig()], [], deepseek_key_present=False)
    assert h["status"] == "severe"
    assert "prices missing for 1/2" in h["severe"][0]


def test_one_missing_price_is_only_degraded():
    board = [_sig(price=None)] + [_sig() for _ in range(9)]
    h = assess(board, [], deepseek_key_present=False)
    assert h["status"] == "degraded" and h["severe"] == []


def test_no_summaries_with_key_is_severe():
    """The other half of the outage: a stale DEEPSEEK_API_KEY killed every summary."""
    h = assess([_sig(summary=""), _sig(summary=None)], [], deepseek_key_present=True)
    assert h["status"] == "severe"
    assert "DeepSeek" in h["severe"][0]


def test_no_summaries_without_key_is_fine():
    h = assess([_sig(summary="")], [], deepseek_key_present=False)
    assert h["status"] == "ok"


def test_degrade_events_surface_as_problems():
    h = assess([_sig()], [{"what": "news NVDA", "reason": "timeout"}],
               deepseek_key_present=False)
    assert h["status"] == "degraded" and h["problems"] == ["news NVDA — timeout"]


# --- degrade event log ----------------------------------------------------

def test_warn_records_an_event(capsys):
    degrade.warn("price NVDA", "boom")
    assert degrade.events() == [{"what": "price NVDA", "reason": "boom"}]
    degrade.reset()
    assert degrade.events() == []
    capsys.readouterr()


# --- publishing -----------------------------------------------------------

def test_write_outputs_publishes_health_json(tmp_path):
    health = {"status": "degraded", "severe": [], "problems": ["x"], "board_size": 1}
    write_outputs("<html></html>", {"board": ["AAA"], "health": health},
                  out_dir=str(tmp_path))
    assert json.loads((tmp_path / "health.json").read_text()) == health
    assert json.loads((tmp_path / "data.json").read_text())["health"] == health


# --- alert email ----------------------------------------------------------

def test_health_email_lists_findings_and_escapes():
    h = {"status": "severe", "severe": ["prices missing for 15/15 board names"],
         "problems": ["price <AAA> — boom"], "board_size": 15}
    html = build_health_alert_email("2026-08-07", h)
    assert "prices missing for 15/15" in html
    assert "&lt;AAA&gt;" in html and "<AAA>" not in html


def test_health_alert_requires_creds(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("EMAIL_RECIPIENTS", raising=False)
    assert send_health_alert("2026-08-07", {"status": "severe",
                                            "severe": ["x"], "problems": []}) is False
