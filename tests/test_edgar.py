# tests/test_edgar.py
import pathlib
import pytest
from radar.monitors import edgar
from radar.monitors.edgar import EdgarMonitor

ATOM = pathlib.Path("tests/fixtures/edgar_atom.xml").read_text()
BUY = pathlib.Path("tests/fixtures/edgar_form4_buy.xml").read_text()
SALE = pathlib.Path("tests/fixtures/edgar_form4_sale.xml").read_text()
INDEX = pathlib.Path("tests/fixtures/edgar_index.json").read_text()


def test_parse_atom_extracts_entries():
    entries = edgar.parse_atom(ATOM)
    assert len(entries) == 5                              # 3 Form 4 + 1 prospectus + 1 dup
    assert entries[0].accession == "000111-26-000001"
    assert entries[0].doc_url.endswith("000111-26-000001-index.htm")
    assert entries[0].published.startswith("2026-06-26T")
    assert entries[0].form_type == "4"                    # category term captured
    assert any(e.form_type == "424B2" for e in entries)   # non-Form-4 entries are parsed too


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
    small_buy = BUY.replace("<value>10000</value>", "<value>750</value>")   # 750*120 = 90k
    # route by the accession-nodash folder embedded in each resolved URL
    form4_by_folder = {"00011126000001": BUY, "00022226000002": small_buy,
                       "00033326000003": SALE}

    def fake_get(url, ua):
        if "getcurrent" in url:
            return ATOM
        if url.endswith("index.json"):
            return INDEX
        if url.endswith("form4.xml"):
            for folder, doc in form4_by_folder.items():
                if folder in url:
                    return doc
        return ""

    monkeypatch.setattr(edgar, "_http_get", fake_get)
    m = EdgarMonitor(min_usd=1_000_000, transaction_codes=["P"], max_age_h=24,
                     user_agent="reddit-signal-radar/0.1 (contact: x@example.com)",
                     sleep_seconds=0)
    signals, evaluated = m.fetch_new(set())
    assert len(evaluated) == 4                       # 4 unique accessions (the dup is collapsed)
    assert evaluated.count("000111-26-000001") == 1  # filing listed twice -> processed once
    assert "000444-26-000004" in evaluated           # the 424B2 is recorded in the cursor...
    assert len(signals) == 1                          # ...but only the big Form-4 buy alerts
    assert signals[0].tickers == ["ACME"]
    assert "ACME" in signals[0].summary and "1,200,000" in signals[0].summary


def test_fetch_new_debug_logs_resolved_urls_and_summary(monkeypatch, capsys):
    form4_by_folder = {"00011126000001": BUY, "00022226000002": SALE,
                       "00033326000003": SALE}

    def fake_get(url, ua):
        if "getcurrent" in url:
            return ATOM
        if url.endswith("index.json"):
            return INDEX
        if url.endswith("form4.xml"):
            for folder, doc in form4_by_folder.items():
                if folder in url:
                    return doc
        return ""

    monkeypatch.setattr(edgar, "_http_get", fake_get)
    monkeypatch.setenv("EDGAR_DEBUG", "1")
    m = EdgarMonitor(min_usd=1_000_000, transaction_codes=["P"], max_age_h=24,
                     user_agent="ua", sleep_seconds=0)
    m.fetch_new(set())
    err = capsys.readouterr().err
    assert "/00011126000001/form4.xml" in err          # per-filing resolved doc URL logged
    assert "ACME P $1,200,000" in err                  # per-filing parse outcome logged
    assert "EDGAR: examined 5 feed entries" in err     # always-on health summary
    assert "form4 3" in err and "resolved 3" in err and "parsed 3" in err


def test_fetch_new_summary_prints_without_debug(monkeypatch, capsys):
    # index.json fetch returns "" -> nothing resolves; debug off -> no per-filing lines,
    # but the one-line health summary still prints every run.
    monkeypatch.setattr(edgar, "_http_get",
                        lambda url, ua: ATOM if "getcurrent" in url else "")
    monkeypatch.delenv("EDGAR_DEBUG", raising=False)
    m = EdgarMonitor(min_usd=1, transaction_codes=["P"], max_age_h=24, user_agent="ua",
                     sleep_seconds=0)
    m.fetch_new(set())
    err = capsys.readouterr().err
    assert "EDGAR: examined 5 feed entries" in err and "resolved 0" in err
    assert " -> " not in err                            # no per-filing debug detail


def test_form4_url_resolves_root_xml_via_index_json(monkeypatch):
    monkeypatch.setattr(edgar, "_http_get",
                        lambda url, ua: INDEX if url.endswith("index.json") else "")
    m = EdgarMonitor(min_usd=1, transaction_codes=["P"], max_age_h=24, user_agent="ua")
    e = edgar.EdgarEntry(
        accession="000111-26-000001",
        doc_url="https://www.sec.gov/Archives/edgar/data/111/00011126000001/000111-26-000001-index.htm",
        published="2026-06-26T12:00:00Z")
    url = m._form4_url(e)
    assert url.endswith("/00011126000001/form4.xml")   # root ownership doc...
    assert "xsl" not in url                             # ...not the XSLT-rendered variant


def test_parse_form4_derivative_only_returns_none():
    deriv_only = '''<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerName>Deriv Co</issuerName><issuerTradingSymbol>DRV</issuerTradingSymbol></issuer>
  <reportingOwner><reportingOwnerId><rptOwnerName>Opt Holder</rptOwnerName></reportingOwnerId></reportingOwner>
  <derivativeTable>
    <derivativeTransaction>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>9999</value></transactionShares>
        <transactionPricePerShare><value>500.00</value></transactionPricePerShare>
      </transactionAmounts>
    </derivativeTransaction>
  </derivativeTable>
</ownershipDocument>'''
    assert edgar.parse_form4(deriv_only) is None       # no nonDerivativeTable -> not a buy


@pytest.mark.parametrize("sentinel", ["NONE", "N/A", "NA", "-", ""])
def test_fetch_new_skips_no_ticker_sentinels(monkeypatch, sentinel):
    # Some issuers have no public ticker and report NONE / N/A / etc — never emit a $NONE
    # or $N/A alert, even for a huge open-market (code P) buy.
    from radar.monitors.edgar import Form4
    monkeypatch.setattr(edgar, "_http_get", lambda url, ua: (
        ATOM if "getcurrent" in url else INDEX if url.endswith("index.json") else "<x/>"))
    monkeypatch.setattr(edgar, "parse_form4", lambda xml: Form4(
        ticker=sentinel, issuer="Private Co", owner="Insider", title="Director",
        code="P", shares=100, price=999_999, usd=99_999_900))
    m = EdgarMonitor(min_usd=1, transaction_codes=["P"], max_age_h=24, user_agent="ua",
                     sleep_seconds=0)
    signals, _ = m.fetch_new(set())
    assert signals == []


def test_validate_is_identity():
    from radar.monitors.base import Signal
    m = EdgarMonitor(min_usd=1, transaction_codes=["P"], max_age_h=24, user_agent="ua")
    sigs = [Signal(tickers=["ACME"], summary="x", url="", published="", monitor_key="edgar")]
    assert m.validate(sigs) is sigs                  # no LLM gate for structured sources
