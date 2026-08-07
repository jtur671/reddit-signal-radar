"""Visibility for the pipeline's fail-soft paths.

Every enrichment — prices, news, Wikipedia, DeepSeek — is deliberately fail-soft: a dead
upstream degrades the board instead of killing the run. The cost is silence. The board
lost every price and every DeepSeek summary for a week before anyone noticed, because
each `except` returned an empty value without a word. `warn` keeps the fail-soft
behaviour and leaves one line in the CI log saying what stopped working.
"""
from __future__ import annotations

import sys

_EVENTS: list[dict] = []


def warn(what: str, reason: object = "") -> None:
    """One stderr line for a degraded enrichment. Never raises: warn is called inside
    the except handlers of every fail-soft path, so a broken/closed stderr (or a reason
    whose repr blows up) must not turn a degraded run into a dead one.

    Every warn is also recorded in an in-process event log (see events()) so the run
    can assess its own health at the end instead of relying on a human reading stderr."""
    try:
        text = repr(reason) if isinstance(reason, BaseException) else str(reason)
        _EVENTS.append({"what": what, "reason": text})
        print(f"DEGRADED: {what}" + (f" — {text}" if text else ""), file=sys.stderr)
    except Exception:
        pass


def events() -> list[dict]:
    """Every warn() recorded since process start (or the last reset), oldest first."""
    return list(_EVENTS)


def reset() -> None:
    """Clear the event log — for tests and multi-run processes."""
    _EVENTS.clear()
