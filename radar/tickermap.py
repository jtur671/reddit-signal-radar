"""Ticker -> exact English Wikipedia article title, derived from Wikidata.

Names are not identifiers. Guessing an article from a company name resolved AAPL to
the fruit and SDGR to a dead physicist; for a pageviews ingest that is a silent,
permanent, wrong signal. This module fails CLOSED -- a ticker it cannot resolve gets
no title at all, which downstream renders as nothing.

The ticker lives on a QUALIFIER (pq:P249 on a p:P414 stock-exchange statement), not on
a direct property: the truthy wdt:P249 path has 38 statements, the qualifier path has
17,204. Every successful fetch is vendored to a data-branch snapshot, per cramer.py.
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import requests
import yaml

from radar import degrade

ENDPOINT = "https://query.wikidata.org/sparql"
UA = "reddit-signal-radar/0.1 (open-source ticker signal bot)"

# NYSE, Nasdaq, OTC Markets Group, NYSE American. Scoping is a correctness
# requirement, not an optimization: unscoped, ticker ambiguity is 15.2% and includes
# cross-domain collisions (BA -> Boeing / Bangkok Airways, DTE -> DTE Energy /
# Deutsche Telekom). US-scoped it is 3.6%, and every case is same-company-family.
EXCHANGES = ("wd:Q13677", "wd:Q82059", "wd:Q1930860", "wd:Q846626")

_WHERE = """
  VALUES ?exch { %s }
  ?item p:P414 ?st .
  ?st ps:P414 ?exch .
  ?st pq:P249 ?ticker .
  ?st wikibase:rank ?rank .
  ?sl schema:about ?item ;
      schema:isPartOf <https://en.wikipedia.org/> ;
      schema:name ?enwiki .
  OPTIONAL { ?st pq:P582 ?end . }
""" % " ".join(EXCHANGES)

QUERY = "SELECT ?ticker ?item ?enwiki ?rank ?end WHERE {%s}" % _WHERE
COUNT_QUERY = "SELECT (COUNT(*) AS ?n) WHERE {%s}" % _WHERE

_DEPRECATED = "http://wikiba.se/ontology#DeprecatedRank"


def _val(binding, key):
    node = binding.get(key) if isinstance(binding, dict) else None
    return node.get("value") if isinstance(node, dict) else None


def parse_rows(raw) -> dict[str, str]:
    """{TICKER: exact article title}. Pure, never raises.

    Rules, in order: drop DeprecatedRank; drop statements whose end-date (pq:P582) is
    in the past when a non-ended alternative exists for that ticker; then accept only
    tickers left with exactly one distinct title. A ticker with two live same-family
    candidates is OMITTED, not guessed -- ticker_overrides.yml resolves those."""
    try:
        bindings = raw["results"]["bindings"]
    except (TypeError, KeyError):
        return {}
    if not isinstance(bindings, list):
        return {}

    by_ticker: dict[str, list[tuple[str, bool]]] = {}
    for b in bindings:
        ticker, title = _val(b, "ticker"), _val(b, "enwiki")
        if not ticker or not title:
            continue
        if _val(b, "rank") == _DEPRECATED:
            continue
        by_ticker.setdefault(ticker.upper(), []).append((title, _val(b, "end") is not None))

    out: dict[str, str] = {}
    for ticker, rows in by_ticker.items():
        live = [t for t, ended in rows if not ended]
        candidates = live or [t for t, _ in rows]
        distinct = sorted(set(candidates))
        if len(distinct) == 1:
            out[ticker] = distinct[0]
    return out
