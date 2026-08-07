import sys

from radar.degrade import warn


class _BrokenStream:
    """A stderr whose reader has gone away — every write raises, like a closed pipe."""
    def write(self, *a, **k):
        raise ValueError("I/O operation on closed file")

    def flush(self):
        raise ValueError("I/O operation on closed file")


class _EvilRepr(Exception):
    def __repr__(self):
        raise RuntimeError("repr exploded")


def test_warn_writes_one_stderr_line(capsys):
    warn("prices 2/2 missing", "AAA, BBB")
    assert "DEGRADED: prices 2/2 missing — AAA, BBB" in capsys.readouterr().err


def test_warn_survives_broken_stderr(monkeypatch):
    """warn runs inside the except handlers of every fail-soft path: a broken or
    closed stderr must not turn a degraded run into a dead one."""
    monkeypatch.setattr(sys, "stderr", _BrokenStream())
    warn("prices", RuntimeError("upstream down"))   # must not raise


def test_warn_survives_a_reason_whose_repr_raises():
    warn("deepseek summary", _EvilRepr())           # must not raise
