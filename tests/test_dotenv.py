from radar.dotenv import load_env


def test_load_env_sets_missing_and_never_overrides(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nFOO_NEW=abc\nFOO_EXISTING=fromfile\n\nBAR='quoted'\n")
    monkeypatch.delenv("FOO_NEW", raising=False)
    monkeypatch.setenv("FOO_EXISTING", "fromenv")     # already set -> must win
    load_env(str(env))
    import os
    assert os.environ["FOO_NEW"] == "abc"             # filled in
    assert os.environ["FOO_EXISTING"] == "fromenv"    # not overridden (CI secrets win)
    assert os.environ["BAR"] == "quoted"              # quotes stripped


def test_load_env_missing_file_is_noop(tmp_path):
    load_env(str(tmp_path / "nope.env"))              # must not raise
