from __future__ import annotations
import re
from radar.models import Item, Mention
from radar.universe import Universe

CASHTAG = re.compile(r"\$([A-Za-z]{1,5})\b")
BAREWORD = re.compile(r"\b([A-Z]{1,5})\b")   # uppercase tokens only

def extract_mentions(items: list[Item], universe: Universe) -> list[Mention]:
    out: list[Mention] = []
    for it in items:
        found: set[str] = set()
        for m in CASHTAG.finditer(it.text):
            tok = m.group(1).upper()
            # Cashtags bypass the stoplist (an explicit $AI means the ticker), but
            # must still be a real symbol -- otherwise anyone can mint a fake ticker
            # ($FAKE, $ZZZZ) that pollutes the board and steers the LLM summary.
            if universe.is_symbol(tok):
                found.add(tok)
        for m in BAREWORD.finditer(it.text):
            tok = m.group(1).upper()
            if universe.is_stopword(tok):
                continue
            if universe.is_symbol(tok):
                found.add(tok)
        for ticker in found:
            out.append(Mention(ticker=ticker, item_id=it.id, subreddit=it.subreddit,
                               author=it.author, created_utc=it.created_utc, text=it.text))
    return out
