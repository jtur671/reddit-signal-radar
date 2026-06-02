from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class Item:
    id: str
    kind: str            # "post" | "comment"
    subreddit: str
    author: str
    created_utc: float
    text: str
    score: int
    permalink: str

@dataclass
class Mention:
    ticker: str
    item_id: str
    subreddit: str
    author: str
    created_utc: float
    text: str

@dataclass
class Signal:
    ticker: str
    mentions: int = 0
    distinct_authors: int = 0
    weighted_today: float = 0.0
    baseline_mean: float = 0.0
    baseline_std: float = 0.0
    velocity: float = 0.0
    surprise: float = 0.0
    score: float = 0.0
    pct_bull: float = 0.0
    state: str = "sustained"      # new | hot | sustained | cooling
    themes: list[str] = field(default_factory=list)
    subreddits: list[str] = field(default_factory=list)
    price: float | None = None
    pct_change: float | None = None
    summary: str = ""
