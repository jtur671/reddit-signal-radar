import json
from pathlib import Path
from types import SimpleNamespace

import radar.short_interest as si
from radar import degrade

RAW = json.loads(Path("tests/fixtures/finra_short_interest.json").read_text())


def _cfg(tmp_path, page_size=5000):
    return SimpleNamespace(short_interest=SimpleNamespace(
        snapshot_path=str(tmp_path / "short_interest.json"), page_size=page_size))


def test_parses_days_to_cover_and_shares():
    rows, settlement = si.parse_rows(RAW)
    assert rows["NVDA"]["days_to_cover"] == 2.47
    assert rows["NVDA"]["shares"] == 324052767
    assert settlement == "2026-07-31"


def test_sentinel_days_to_cover_is_filtered():
    """999.99 means zero average volume, not a 999-day cover. Unfiltered it tops
    every ranking."""
    rows, _ = si.parse_rows(RAW)
    assert "AAALF" not in rows


def test_parse_rows_never_raises():
    for junk in (None, {}, "nope", [{"symbolCode": None}], [{"bad": 1}]):
        rows, settlement = si.parse_rows(junk)
        assert rows == {} and settlement == ""


def test_refreshes_only_when_settlement_advances(monkeypatch, tmp_path):
    """Twice-monthly data. Re-pulling 22k rows daily is waste."""
    snap = tmp_path / "short_interest.json"
    snap.write_text(json.dumps({"schema": 1, "settlement": "2026-07-31",
                                "rows": {"NVDA": {"days_to_cover": 2.47, "shares": 1}}}))
    calls = []
    monkeypatch.setattr(si, "_post_json", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: "2026-07-31")
    rows, settlement = si.fetch_short_interest(_cfg(tmp_path), "2026-08-17")
    assert calls == [], "same settlement date must not trigger a full pull"
    assert rows["NVDA"]["days_to_cover"] == 2.47 and settlement == "2026-07-31"


def test_upstream_down_serves_snapshot_and_warns(monkeypatch, tmp_path):
    snap = tmp_path / "short_interest.json"
    snap.write_text(json.dumps({"schema": 1, "settlement": "2026-07-15",
                                "rows": {"NVDA": {"days_to_cover": 3.0, "shares": 1}}}))
    monkeypatch.setattr(si, "_post_json", lambda *a, **k: None)
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: None)
    rows, settlement = si.fetch_short_interest(_cfg(tmp_path), "2026-08-17")
    assert rows["NVDA"]["days_to_cover"] == 3.0
    assert settlement == "2026-07-15"
    assert any("snapshot" in str(e).lower() for e in degrade.events())


def test_both_gone_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(si, "_post_json", lambda *a, **k: None)
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: None)
    assert si.fetch_short_interest(_cfg(tmp_path), "2026-08-17") == ({}, "")


def test_pagination_walks_until_short_page(monkeypatch, tmp_path):
    """5,000-row cap: a full page means there is more to fetch."""
    pages = [[dict(RAW[0], symbolCode=f"T{i}") for i in range(5000)],
             [dict(RAW[0], symbolCode="LAST")]]
    monkeypatch.setattr(si, "_post_json", lambda *a, **k: pages.pop(0) if pages else [])
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: "2026-08-14")
    rows, _ = si.fetch_short_interest(_cfg(tmp_path), "2026-08-17")
    assert "LAST" in rows, "must keep paging past a full 5000-row page"
