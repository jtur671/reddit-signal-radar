from __future__ import annotations
import json, statistics
from pathlib import Path
from datetime import date

class History:
    """Per-ticker per-day record. Stored as {ticker: {date: {...}}}. Implements INV-2/INV-6."""
    def __init__(self, path: Path, data: dict):
        self.path, self.data = path, data

    @classmethod
    def load(cls, path) -> "History":
        p = Path(path)
        data = json.loads(p.read_text()) if p.exists() and p.read_text().strip() else {}
        return cls(p, data)

    def days_for(self, ticker: str) -> dict:
        return self.data.get(ticker, {})

    def record(self, day, ticker, weighted, raw, authors, pct_bull, score, state):
        self.data.setdefault(ticker, {})[day] = {
            "weighted": weighted, "raw": raw, "authors": authors,
            "pct_bull": pct_bull, "score": score, "state": state}

    def annotate(self, day: str, ticker: str, **fields) -> bool:
        """Merge extra keys (e.g. ts_bull) into an EXISTING day-record. Never creates
        a record: baseline() requires 'weighted' in every day-record, so a ticker not
        scored today simply drops its annotation. Returns whether it merged."""
        rec = self.data.get(ticker, {}).get(day)
        if rec is None:
            return False
        rec.update(fields)
        return True

    def baseline(self, ticker, before: str, days: int, alpha: float) -> tuple[float, float]:
        """EMA mean + population std of weighted counts in the trailing `days`-day
        window STRICTLY before `before`.

        Silent days (no record) are folded in as 0.0, starting from the ticker's
        FIRST in-window appearance, so a ticker that spiked once and then went quiet
        sees its baseline DECAY toward zero day by day. A later resurgence then reads
        as a genuine surprise instead of being suppressed against a stale peak
        (INV-1/INV-6) -- without this, a one-time spike would freeze the baseline for
        the full window and bury real comebacks as 'cooling'. Brand-new tickers are
        not penalised: zero-fill begins at their first appearance, not the window
        edge. An ancient spike outside the trailing window is excluded entirely, so
        the 90-day window is enforced here, not only by the on-disk prune."""
        hist = self.days_for(ticker)
        before_ord = date.fromisoformat(before).toordinal()
        cutoff = before_ord - days
        present = {date.fromisoformat(d).toordinal(): hist[d]["weighted"]
                   for d in hist
                   if cutoff <= date.fromisoformat(d).toordinal() < before_ord}
        if not present:
            return (0.0, 0.0)
        start = min(present)                       # first in-window appearance
        vals = [present.get(o, 0.0) for o in range(start, before_ord)]
        ema = vals[0]
        for v in vals[1:]:
            ema = alpha * v + (1 - alpha) * ema
        std = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        return (float(ema), float(std))

    def prune(self, keep_through: str, days: int):
        cutoff = (date.fromisoformat(keep_through).toordinal() - days)
        for ticker in list(self.data):
            self.data[ticker] = {d: v for d, v in self.data[ticker].items()
                                 if date.fromisoformat(d).toordinal() >= cutoff}
            if not self.data[ticker]:
                del self.data[ticker]

    def save(self):
        self.path.write_text(json.dumps(self.data, indent=0, sort_keys=True))
