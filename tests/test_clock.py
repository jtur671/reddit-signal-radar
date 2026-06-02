from datetime import datetime, timezone
from freezegun import freeze_time
from radar import clock

def test_age_hours_basic():
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc).timestamp()
    created = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc).timestamp()
    assert clock.age_hours(created, now) == 3.0

def test_decay_weight_halves_each_half_life():
    assert clock.decay_weight(0, half_life_hours=24) == 1.0
    assert abs(clock.decay_weight(24, half_life_hours=24) - 0.5) < 1e-9
    assert abs(clock.decay_weight(48, half_life_hours=24) - 0.25) < 1e-9

def test_within_window_excludes_old_content():
    assert clock.within_window(age_h=10, lookback_hours=48) is True
    assert clock.within_window(age_h=49, lookback_hours=48) is False

def test_run_date_is_eastern_calendar_day_dst_safe():
    with freeze_time("2026-06-01 09:30:00"):  # 09:30 UTC == 05:30 ET
        assert clock.run_date("America/New_York") == "2026-06-01"
    with freeze_time("2026-03-08 06:30:00"):
        assert clock.run_date("America/New_York") == "2026-03-08"
