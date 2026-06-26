# tests/test_monitor_entrypoint.py
import json, pathlib
import radar.monitor as mon
from radar.monitors import base
from radar.monitors.base import Signal


def test_fleet_main_writes_alerts_and_sets_output(tmp_path, monkeypatch):
    # Two fake monitors via a stub registry; no network, no email.
    class M:
        def __init__(self, key): self.key = key; self.label = key; self.card_style = key; self.max_age_h = 24
        def fetch_new(self, seen):
            return ([Signal(tickers=["AAA"], summary="s", url="", published="2026-06-26T12:00:00Z",
                            monitor_key=self.key)] if not seen else []), ["x1"]
        def validate(self, s): return s
    monkeypatch.setattr(mon, "build_registry", lambda cfg: [M("trump"), M("edgar")])
    monkeypatch.setattr(mon, "load_config", lambda p: object())
    monkeypatch.setattr(mon, "send_monitor_alert", lambda alert: True)
    monkeypatch.setattr(base, "load_seen", lambda p: [])
    monkeypatch.setattr(base, "save_seen", lambda p, s, cap=200: None)
    written = {}
    monkeypatch.setattr(base, "write_alert",
                        lambda m, sig, ts, data_dir="data": written.__setitem__(m.key, sig.tickers))
    out = tmp_path / "ghout"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert mon.main([]) == 0
    assert written == {"trump": ["AAA"], "edgar": ["AAA"]}
    assert "alert=true" in out.read_text()
