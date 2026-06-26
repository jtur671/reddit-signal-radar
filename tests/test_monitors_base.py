# tests/test_monitors_base.py
import json, pathlib
from radar.monitors import base
from radar.monitors.base import Signal


class FakeMonitor:
    """Two source records ('a','b'); 'b' is the salient signal. Records every id seen."""
    key = "fake"; label = "Fake Alert"; card_style = "fake"; max_age_h = 24

    def __init__(self):
        self.validated = False

    def fetch_new(self, seen):
        ids = ["a", "b"]
        new = [i for i in ids if i not in seen]
        sigs = [Signal(tickers=["ZZZ"], summary=f"sig {i}", url="http://x",
                       published="2026-06-26T12:00:00Z", monitor_key=self.key)
                for i in new]
        return sigs, ids                      # all ids evaluated -> cursor advances past both

    def validate(self, signals):
        self.validated = True
        return signals                        # identity (structured-style)


def test_run_fleet_writes_alert_advances_cursor_and_reports_fired(tmp_path):
    m = FakeMonitor()
    fired = base.run_fleet([m], now_iso="2026-06-26T12:30:00Z", data_dir=str(tmp_path))
    assert fired is True
    alert = json.loads(pathlib.Path(base.alert_path("fake", str(tmp_path))).read_text())
    assert alert["monitor_key"] == "fake" and alert["label"] == "Fake Alert"
    assert alert["card_style"] == "fake" and alert["detected_at"] == "2026-06-26T12:30:00Z"
    assert alert["tickers"] == ["ZZZ"]
    seen = json.loads(pathlib.Path(base.seen_path("fake", str(tmp_path))).read_text())
    assert set(seen) == {"a", "b"}
    assert m.validated is True                 # validation step ran


def test_run_fleet_dedups_second_run(tmp_path):
    base.run_fleet([FakeMonitor()], now_iso="2026-06-26T12:30:00Z", data_dir=str(tmp_path))
    fired2 = base.run_fleet([FakeMonitor()], now_iso="2026-06-26T13:00:00Z", data_dir=str(tmp_path))
    assert fired2 is False                     # everything already seen -> no new alert


def test_run_fleet_invokes_on_alert_callback(tmp_path):
    calls = []
    base.run_fleet([FakeMonitor()], now_iso="2026-06-26T12:30:00Z",
                   on_alert=lambda mon, sig: calls.append((mon.key, sig.tickers)),
                   data_dir=str(tmp_path))
    assert calls == [("fake", ["ZZZ"])]
