# radar/monitors/edgar.py
"""EDGAR insider-buy monitor (structured). Pulls SEC's free 'latest Form 4 filings' Atom
feed, parses each filing's ownership XML, and alerts on open-market PURCHASES (code 'P')
above a dollar floor — MARKET-WIDE (no universe restriction). The ticker is a filed field,
so no LLM inference is needed (validate() is identity). One alert per tick: the largest buy."""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import requests

from radar.monitors.base import Signal

ATOM_URL = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4"
            "&company=&dateb=&owner=include&count=100&output=atom")
_ACC_PREFIX = "accession-number="


@dataclass
class EdgarEntry:
    accession: str
    doc_url: str           # the filing index page
    published: str         # ISO-8601 'Z'


@dataclass
class Form4:
    ticker: str
    issuer: str
    owner: str
    title: str
    code: str
    shares: float
    price: float
    usd: float


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]      # strip XML namespace


def _to_z(s: str) -> str:
    """Normalize an Atom <updated> timestamp to ISO-8601 'Z'; '' if unparseable."""
    from email.utils import parsedate_to_datetime
    from datetime import datetime, timezone
    s = (s or "").strip()
    for parse in (
        lambda v: datetime.fromisoformat(v.replace("Z", "+00:00")),
        lambda v: parsedate_to_datetime(v),
    ):
        try:
            return parse(s).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            continue
    return ""


def parse_atom(xml_text: str) -> list[EdgarEntry]:
    """Parse the EDGAR 'getcurrent' Atom feed. Never raises; [] on bad XML."""
    out: list[EdgarEntry] = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return out
    for entry in root.iter():
        if _localname(entry.tag) != "entry":
            continue
        acc, href, updated = "", "", ""
        for child in entry:
            name = _localname(child.tag)
            if name == "id" and _ACC_PREFIX in (child.text or ""):
                acc = child.text.split(_ACC_PREFIX, 1)[1].strip()
            elif name == "link" and child.get("href"):
                href = child.get("href")
            elif name == "updated":
                updated = child.text or ""
        if acc:
            out.append(EdgarEntry(accession=acc, doc_url=href, published=_to_z(updated)))
    return out


def _first_value(node) -> str:
    """Return the text of a child <value> if present, else the node's own text."""
    if node is None:
        return ""
    for c in node:
        if _localname(c.tag) == "value":
            return (c.text or "").strip()
    return (node.text or "").strip()


def parse_form4(xml_text: str) -> Form4 | None:
    """Parse a Form-4 ownership document; return the first non-derivative transaction as a
    Form4, or None if none is parseable. Never raises."""
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return None
    nodes = {}
    issuer = owner = title = ticker = ""
    for el in root.iter():
        name = _localname(el.tag)
        if name == "issuerTradingSymbol":
            ticker = (el.text or "").strip().upper()
        elif name == "issuerName":
            issuer = (el.text or "").strip()
        elif name == "rptOwnerName":
            owner = (el.text or "").strip()
        elif name == "officerTitle" and (el.text or "").strip():
            title = (el.text or "").strip()
        elif name == "isDirector" and (el.text or "").strip() in ("1", "true") and not title:
            title = "Director"
        elif name in ("transactionCode", "transactionShares", "transactionPricePerShare"):
            nodes.setdefault(name, el)
    code = (nodes.get("transactionCode").text or "").strip() if nodes.get("transactionCode") is not None else ""
    try:
        shares = float(_first_value(nodes.get("transactionShares")) or 0)
        price = float(_first_value(nodes.get("transactionPricePerShare")) or 0)
    except ValueError:
        return None
    if not ticker or not code:
        return None
    return Form4(ticker=ticker, issuer=issuer, owner=owner, title=title or "Insider",
                 code=code, shares=shares, price=price, usd=shares * price)


def _http_get(url: str, ua: str) -> str:
    """GET with EDGAR-friendly retry/backoff. Never raises; '' on failure."""
    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": ua}, timeout=20)
            if r.status_code == 200:
                return r.text
            if r.status_code in (429, 500, 502, 503):
                time.sleep(1.0 * (2 ** attempt)); continue
            return ""
        except requests.RequestException:
            time.sleep(1.0 * (2 ** attempt))
    return ""


class EdgarMonitor:
    def __init__(self, *, min_usd: float, transaction_codes, max_age_h: int, user_agent: str,
                 key: str = "edgar", label: str = "📄 Insider Buy", card_style: str = "insider",
                 max_entries: int = 60):
        self.key = key
        self.label = label
        self.card_style = card_style
        self.min_usd = float(min_usd)
        self.codes = set(transaction_codes)
        self.max_age_h = max_age_h
        self.user_agent = user_agent
        self.max_entries = max_entries

    def _form4_url(self, entry: EdgarEntry) -> str:
        """Derive the raw Form-4 XML URL from the filing's accession number.
        EDGAR stores it under the accession folder; the primary doc is <acc-nodashes>.xml."""
        acc = entry.accession
        nodash = acc.replace("-", "")
        # accession format CIK?-YY-NNNNNN; the data folder uses the filer CIK from doc_url.
        # doc_url: .../Archives/edgar/data/<cik>/<acc-nodash>-index.htm
        base = entry.doc_url.rsplit("/", 1)[0]
        return f"{base}/{nodash}.xml"

    def fetch_new(self, seen):
        atom = _http_get(ATOM_URL, self.user_agent)
        entries = parse_atom(atom)[: self.max_entries]
        buys, evaluated = [], []
        for e in entries:
            evaluated.append(e.accession)
            if e.accession in seen:
                continue
            f = parse_form4(_http_get(self._form4_url(e), self.user_agent))
            if not f or f.code not in self.codes or f.usd < self.min_usd:
                continue
            summary = (f"Insider buy — {f.title} bought {f.shares:,.0f} sh of ${f.ticker} "
                       f"(~${f.usd:,.0f}, Form 4)")
            buys.append((f.usd, Signal(tickers=[f.ticker], summary=summary, url=e.doc_url,
                                       published=e.published, monitor_key=self.key,
                                       link_text="View filing ↗")))
        buys.sort(key=lambda t: t[0], reverse=True)        # largest $ first == most-salient-first
        return [s for _, s in buys], evaluated

    def validate(self, signals):
        return signals                                      # structured: no LLM gate
