import json
from pathlib import Path
from radar.plays_log import append_picks, load_picks
from radar.models import Signal

def _sig(t):
    return Signal(ticker=t, mentions=42, state="hot", vel_24h=3.2)

def test_append_creates_file_and_dedupes(tmp_path):
    p = tmp_path / "plays_log.json"
    picks = [{"ticker": "AAA", "thesis": "t", "risk": "r", "conviction": "high"}]
    by = {"AAA": _sig("AAA")}
    assert append_picks(p, "2026-08-08", picks, by) == 1
    assert append_picks(p, "2026-08-08", picks, by) == 0          # same day+ticker -> no dup
    data = json.loads(p.read_text())
    assert len(data["picks"]) == 1
    row = data["picks"][0]
    assert row["date"] == "2026-08-08" and row["ticker"] == "AAA"
    assert row["mentions"] == 42 and row["state"] == "hot" and row["vel"] == 3.2

def test_append_next_day_appends(tmp_path):
    p = tmp_path / "plays_log.json"
    picks = [{"ticker": "AAA", "thesis": "t", "risk": "r", "conviction": "low"}]
    append_picks(p, "2026-08-08", picks, {})
    assert append_picks(p, "2026-08-09", picks, {}) == 1
    assert len(load_picks(p)) == 2

def test_load_tolerates_missing_and_corrupt(tmp_path):
    assert load_picks(tmp_path / "nope.json") == []
    bad = tmp_path / "bad.json"; bad.write_text("{not json")
    assert load_picks(bad) == []

def test_corrupt_file_does_not_lose_new_picks(tmp_path):
    bad = tmp_path / "plays_log.json"; bad.write_text("{not json")
    picks = [{"ticker": "BBB", "thesis": "t", "risk": "", "conviction": ""}]
    assert append_picks(bad, "2026-08-08", picks, {}) == 1        # corrupt -> start fresh
    assert [r["ticker"] for r in load_picks(bad)] == ["BBB"]

def test_append_stamps_crypto_field(tmp_path):
    p = tmp_path / "plays_log.json"
    picks = [{"ticker": "ETH", "thesis": "t", "risk": "r", "conviction": "high"},
             {"ticker": "AAA", "thesis": "t", "risk": "r", "conviction": "high"}]
    append_picks(p, "2026-08-08", picks, {}, crypto_tickers={"ETH"})
    rows = {r["ticker"]: r for r in load_picks(p)}
    assert rows["ETH"]["crypto"] is True
    assert rows["AAA"]["crypto"] is False

def test_append_without_crypto_tickers_defaults_false(tmp_path):
    p = tmp_path / "plays_log.json"
    picks = [{"ticker": "AAA", "thesis": "t", "risk": "r", "conviction": "high"}]
    append_picks(p, "2026-08-08", picks, {})
    row = load_picks(p)[0]
    assert row["crypto"] is False
