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
    upvotes: int = 0              # ApeWisdom upvote total (aggregate path); 0 for raw-mention path
    mentions_24h_ago: int = 0     # ApeWisdom prior-day mention count
    vel_24h: float | None = None  # display velocity = mentions / mentions_24h_ago; None -> NEW
    name: str = ""                # company/asset name (from ApeWisdom)
    about_desc: str = ""          # one-line Wikipedia description ("American IT company")
    about_extract: str = ""       # fuller Wikipedia summary sentence(s)
    headlines: list[str] = field(default_factory=list)  # recent news headlines (the catalyst)
    days_running: int | None = None  # Still Running lane: days since the most recent breakout
    short_ratio: float | None = None  # FINRA daily ShortVolume/TotalVolume (0..1)
    pc_ratio: float | None = None     # CBOE put/call volume ratio (top movers only)
    uoa: bool = False                 # unusual options activity flag (top movers only)
    cramer: str = ""                  # latest Mad Money sentiment enum ("" = no recent mention)
    composite: int | None = None      # 0-100 blended score (None until composite lands)
    components: dict = field(default_factory=dict)  # composite inputs, each 0-100 or None
