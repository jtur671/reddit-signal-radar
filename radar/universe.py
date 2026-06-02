from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass

@dataclass
class Universe:
    symbols: set[str]
    stopwords: set[str]

    @classmethod
    def load(cls, universe_path: Path, stoplist_path: Path) -> "Universe":
        syms = {s.strip().upper() for s in Path(universe_path).read_text().split() if s.strip()}
        stops = {s.strip().upper() for s in Path(stoplist_path).read_text().split() if s.strip()}
        return cls(symbols=syms, stopwords=stops)

    def is_symbol(self, tok: str) -> bool:
        return tok.upper() in self.symbols

    def is_stopword(self, tok: str) -> bool:
        return tok.upper() in self.stopwords
