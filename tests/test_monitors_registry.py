# tests/test_monitors_registry.py
from radar.config import load_config
from radar.monitors import build_registry
from radar.monitors.prose import ProseMonitor
from radar.monitors.edgar import EdgarMonitor


def test_registry_has_trump_and_edgar():
    reg = build_registry(load_config("config.yaml"))
    keys = [m.key for m in reg]
    assert keys == ["trump", "edgar"]
    trump_m = next(m for m in reg if m.key == "trump")
    edgar_m = next(m for m in reg if m.key == "edgar")
    assert isinstance(trump_m, ProseMonitor) and isinstance(edgar_m, EdgarMonitor)
    assert edgar_m.min_usd == 1_000_000 and edgar_m.codes == {"P"}
    assert trump_m.card_style == "trump" and edgar_m.card_style == "insider"
