import json
from radar.history import History

def test_update_and_baseline(tmp_path):
    p = tmp_path/"h.json"; p.write_text("{}")
    h = History.load(p)
    for day, val in [("2026-05-29",10),("2026-05-30",12),("2026-05-31",11)]:
        h.record(day, "IREN", weighted=val, raw=val, authors=val, pct_bull=60, score=1, state="hot")
    mean, std = h.baseline("IREN", before="2026-06-01", days=90, alpha=0.3)
    assert mean > 0 and std >= 0

def test_baseline_honors_days_window(tmp_path):
    # An ancient spike outside the trailing `days` window must NOT pollute the
    # baseline, even if prune() hasn't run yet (anti-staleness: 90-day window
    # enforced inside baseline, not only on disk).
    p = tmp_path/"h.json"; p.write_text("{}")
    h = History.load(p)
    h.record("2025-01-01","IREN",1000,1000,1000,50,1,"hot")   # far outside 90d
    h.record("2026-05-31","IREN",10,10,10,50,1,"hot")          # in-window
    mean, std = h.baseline("IREN", before="2026-06-01", days=90, alpha=0.3)
    assert mean == 10.0 and std == 0.0   # only the in-window day counts

def test_unknown_ticker_baseline_is_zero(tmp_path):
    h = History.load((tmp_path/"h.json")); (tmp_path/"h.json").write_text("{}")
    assert h.baseline("ZZZ", before="2026-06-01", days=90, alpha=0.3) == (0.0, 0.0)

def test_prune_drops_old_days(tmp_path):
    p = tmp_path/"h.json"; p.write_text("{}")
    h = History.load(p)
    h.record("2026-01-01","IREN",1,1,1,50,1,"hot")
    h.record("2026-06-01","IREN",5,5,5,50,1,"hot")
    h.prune(keep_through="2026-06-01", days=90)
    assert "2026-01-01" not in h.days_for("IREN")

def test_record_is_idempotent_per_day(tmp_path):
    p = tmp_path/"h.json"; p.write_text("{}")
    h = History.load(p)
    h.record("2026-06-01","IREN",5,5,5,50,1,"hot")
    h.record("2026-06-01","IREN",9,9,9,50,1,"hot")  # rerun same day overwrites
    assert h.days_for("IREN")["2026-06-01"]["weighted"] == 9
