from __future__ import annotations
from pathlib import Path
import yaml

class Themes:
    def __init__(self, raw: dict):
        self.raw = raw
        self._by_ticker: dict[str, list[str]] = {}
        for key, t in raw.items():
            for sym in t.get("seeds", []):
                self._by_ticker.setdefault(sym.upper(), []).append(t["label"])

    @classmethod
    def load(cls, path: Path) -> "Themes":
        return cls(yaml.safe_load(Path(path).read_text()) or {})

    def themes_for(self, ticker: str) -> list[str]:
        return self._by_ticker.get(ticker.upper(), [])

    def all_seed_tickers(self) -> set[str]:
        return set(self._by_ticker.keys())
