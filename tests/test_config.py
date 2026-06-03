from radar.config import load_config
def test_load_config():
    c = load_config("config.yaml")
    assert c.half_life_hours == 24 and c.noise_floor.min_mentions == 5
    assert "hot" in c.fetch.listings

def test_still_running_config_block():
    c = load_config("config.yaml")
    assert c.still_running.lookback_days == 3
    assert c.still_running.max_items == 5
    assert c.still_running.velocity_cap == 10
