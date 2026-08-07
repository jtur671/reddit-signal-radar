"""Post-run self-assessment — the radar's radar on itself.

The board is consumed by downstream trader agents, so a silently degraded run (every
price blank, every summary empty) is worse than no run at all. assess() inspects the
finished board plus the degrade-event log and returns a machine-readable health block
that is published alongside the board (out/health.json and the `health` key in
data.json) so consumers can gate on `status` instead of trusting whatever rendered.

Statuses: "ok" (clean run), "degraded" (something failed but the board is usable),
"severe" (the board is materially wrong or empty — also triggers an alert email).
"""
from __future__ import annotations

# A board missing at least this fraction of its prices is severe: the week-long
# outage this module exists to catch blanked 100% of them.
SEVERE_PRICE_MISS = 0.5


def assess(board, events: list[dict], deepseek_key_present: bool,
           sources: dict | None = None) -> dict:
    """Health block for a finished run. `board` is the rendered top-N signal list
    (objects with .price and .summary); `events` is radar.degrade.events()."""
    severe: list[str] = []
    problems: list[str] = []

    if not board:
        severe.append("board is empty — upstream mention feed returned nothing")
    else:
        missing = sum(1 for s in board if s.price is None)
        rate = missing / len(board)
        if rate >= SEVERE_PRICE_MISS:
            severe.append(f"prices missing for {missing}/{len(board)} board names")
        elif missing:
            problems.append(f"prices missing for {missing}/{len(board)} board names")

        if deepseek_key_present and all(not (s.summary or "") for s in board):
            severe.append("DeepSeek produced no summaries despite a configured key")

    problems += [f"{e['what']}" + (f" — {e['reason']}" if e.get("reason") else "")
                 for e in events]

    status = "severe" if severe else ("degraded" if problems else "ok")
    return {"status": status, "severe": severe, "problems": problems,
            "board_size": len(board), "sources": dict(sources or {})}
