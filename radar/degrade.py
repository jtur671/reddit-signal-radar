"""Visibility for the pipeline's fail-soft paths.

Every enrichment — prices, news, Wikipedia, DeepSeek — is deliberately fail-soft: a dead
upstream degrades the board instead of killing the run. The cost is silence. The board
lost every price and every DeepSeek summary for a week before anyone noticed, because
each `except` returned an empty value without a word. `warn` keeps the fail-soft
behaviour and leaves one line in the CI log saying what stopped working.
"""
from __future__ import annotations

import sys


def warn(what: str, reason: object = "") -> None:
    """One stderr line for a degraded enrichment. Never raises."""
    text = repr(reason) if isinstance(reason, BaseException) else str(reason)
    print(f"DEGRADED: {what}" + (f" — {text}" if text else ""), file=sys.stderr)
