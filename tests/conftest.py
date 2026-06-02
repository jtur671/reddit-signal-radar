import pytest


@pytest.fixture(autouse=True)
def _no_real_dotenv(monkeypatch):
    """Hermeticity guard: neutralize the .env loader in both entrypoints so a developer's
    local .env (real API keys) can never leak into tests and trigger live network calls."""
    import radar.run
    import radar.monitor
    monkeypatch.setattr(radar.run, "load_env", lambda *a, **k: None)
    monkeypatch.setattr(radar.monitor, "load_env", lambda *a, **k: None)
