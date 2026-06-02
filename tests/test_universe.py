from radar.universe import Universe

def test_universe_loads_and_filters(tmp_path):
    (tmp_path / "u.txt").write_text("IREN\nHIVE\nBTC\n")
    (tmp_path / "stop.txt").write_text("DD YOLO AI\n")
    u = Universe.load(tmp_path / "u.txt", tmp_path / "stop.txt")
    assert u.is_symbol("IREN") and u.is_symbol("BTC")
    assert not u.is_symbol("MSFT")        # not in this tiny universe
    assert u.is_stopword("DD") and u.is_stopword("AI")
