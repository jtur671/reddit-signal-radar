from radar.themes import Themes

def test_tagging(tmp_path):
    (tmp_path/"t.yaml").write_text(
        "ai_compute:\n  label: AI Compute\n  seeds: [IREN, HIVE]\n  keywords: [hpc]\n"
        "meme:\n  label: Meme\n  seeds: [GME]\n  keywords: [moon]\n")
    th = Themes.load(tmp_path/"t.yaml")
    assert th.themes_for("IREN") == ["AI Compute"]
    assert th.themes_for("GME") == ["Meme"]
    assert th.themes_for("ZZZZ") == []
    assert "IREN" in th.all_seed_tickers()
