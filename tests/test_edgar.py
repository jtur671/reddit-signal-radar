# tests/test_edgar.py
import pathlib
from radar.monitors import edgar
from radar.monitors.edgar import EdgarMonitor

ATOM = pathlib.Path("tests/fixtures/edgar_atom.xml").read_text()
BUY = pathlib.Path("tests/fixtures/edgar_form4_buy.xml").read_text()
SALE = pathlib.Path("tests/fixtures/edgar_form4_sale.xml").read_text()


def test_parse_atom_extracts_entries():
    entries = edgar.parse_atom(ATOM)
    assert len(entries) == 3
    assert entries[0].accession == "000111-26-000001"
    assert entries[0].doc_url.endswith("000111-26-000001-index.htm")
    assert entries[0].published.startswith("2026-06-26T")


def test_parse_atom_malformed_returns_empty():
    assert edgar.parse_atom("<<not xml>>") == []
    assert edgar.parse_atom("") == []


def test_parse_form4_buy_fields_and_usd():
    f = edgar.parse_form4(BUY)
    assert f is not None
    assert f.ticker == "ACME" and f.code == "P"
    assert f.shares == 10000 and f.price == 120.0 and f.usd == 1_200_000
    assert f.title == "Director"


def test_parse_form4_sale_is_code_s():
    f = edgar.parse_form4(SALE)
    assert f is not None and f.code == "S"


def test_fetch_new_keeps_only_large_buys_sorted_by_usd(monkeypatch):
    # Map each accession -> a fixture: big buy ($1.2M), small buy ($90k), a sale.
    small_buy = BUY.replace("<value>10000</value>", "<value>750</value>")   # 750*120 = 90k
    by_acc = {"000111-26-000001": BUY, "000222-26-000002": small_buy,
              "000333-26-000003": SALE}
    monkeypatch.setattr(edgar, "_http_get", lambda url, ua: ATOM if "getcurrent" in url
                        else by_acc[[a for a in by_acc if a in url][0]])
    # form4 doc url is derived from the index url; make derivation a no-op passthrough for the test
    monkeypatch.setattr(EdgarMonitor, "_form4_url", lambda self, e: e.accession)
    m = EdgarMonitor(min_usd=1_000_000, transaction_codes=["P"], max_age_h=24,
                     user_agent="reddit-signal-radar/0.1 (contact: x@example.com)")
    signals, evaluated = m.fetch_new(set())
    assert len(evaluated) == 3                       # all three accessions examined
    assert len(signals) == 1                         # small buy below floor, sale filtered
    assert signals[0].tickers == ["ACME"]
    assert "ACME" in signals[0].summary and "1,200,000" in signals[0].summary


def test_validate_is_identity():
    from radar.monitors.base import Signal
    m = EdgarMonitor(min_usd=1, transaction_codes=["P"], max_age_h=24, user_agent="ua")
    sigs = [Signal(tickers=["ACME"], summary="x", url="", published="", monitor_key="edgar")]
    assert m.validate(sigs) is sigs                  # no LLM gate for structured sources
