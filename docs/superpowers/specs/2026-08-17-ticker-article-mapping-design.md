---
project: Reddit Signal Radar
phase: E2a — Ticker→article mapping
spec: design
date: 2026-08-17
status: draft (awaiting owner review)
research: [[2026-08-17-community-mining]]
---

# E2a — Ticker→article mapping

Replace the name-guessing Wikipedia lookup with a Wikidata-derived exact-title map.
Fixes a live wrong-entity bug on the dashboard, and is the prerequisite for E2's
pageviews ingest — pageviews are fetched **per exact article title**, so a wrong title
is a wrong signal, silently, forever.

## 1. Why

`radar/about.py` maps a ticker to a Wikipedia article by taking the **company name**
from ApeWisdom and hitting the REST summary endpoint. Names are not identifiers. The
production cache on `origin/data` (420 tickers, measured 2026-08-17) is **59.3%
populated and 13.7% wrong** — 34 of 249 resolved entries point at the wrong entity.

These are live on the board right now:

| Ticker | Resolves to | Wikipedia says |
|---|---|---|
| `AAPL` | Apple | Edible fruit |
| `ADBE` | Adobe | Building material of earth and organic materials |
| `HTZ` | Hertz | SI unit of frequency |
| `CAT` | Caterpillar | Larva of a butterfly or moth |
| `ID` | Everest | Earth's highest mountain |
| `SDGR` | Schrödinger | Austrian–Irish physicist (1887–1961) |
| `UUUU` | Energy Fuels | Academic journal |
| `ORCL` | Oracle | Provider of prophecies or insights |
| `SNOW` | Snowflake | Ice crystals that fall as snow |
| `DIS` | Walt Disney | American animator, producer (1901–1966) |
| `LLY` | Eli Lilly | American pharmacist, Union Army officer |

### 1.1 Why this blocks E2, not just the About modal

E2 fetches Wikimedia pageviews per article title. A wrong title yields a **plausible,
well-formed, entirely fictitious attention series**. Measured against the live
Wikimedia API (2026-08-01→10, daily mean):

| Ticker | Current title | views/day | Correct title | views/day |
|---|---|---|---|---|
| `TSLA` | Tesla | 197 | Tesla, Inc. | **2,857** (14×) |
| `AAPL` | Apple | 2,317 | Apple Inc. | 5,292 |
| `ORCL` | Oracle | 473 | Oracle Corporation | 2,248 |
| `LLY` | Eli Lilly | 265 | Eli Lilly and Company | 1,241 |
| `SDGR` | **Erwin Schrödinger** | **988** | Schrödinger, Inc. | **41** |
| `MVIS` | **Microvision** (1979 game console) | 82 | *(no article)* | — |

`SDGR` is the case that decides the design: the current mapping would feed ~988
physics-class pageviews/day into a biotech attention score whose true magnitude is 41 —
a **24× noise-to-signal inversion**, in the same direction every day, invisible to every
downstream consumer. `MVIS` would inject retro-gaming traffic into a meme-stock signal.

**A missing series is a non-event. A wrong series is silent permanent corruption.**
Every rule below follows from that asymmetry.

## 2. Design

### 2.1 The ticker lives on a qualifier, not a property

Wikidata's P249 (ticker symbol) is documented as *"qualifier for P414"* (stock
exchange). Measured statement counts:

| Path | Statements |
|---|---|
| `?item wdt:P249 ?ticker` (truthy) | 38 |
| `?item p:P249 ?st` (main statement) | 38 |
| `?item p:P414 ?st . ?st pq:P249 ?ticker` (**qualifier**) | **17,204** |

The direct path is unusable. This distinction is the entire query.

### 2.2 The query

Scoped to four US exchanges, requiring an English Wikipedia sitelink:

```sparql
SELECT ?ticker ?item ?enwiki ?rank ?end WHERE {
  VALUES ?exch { wd:Q13677 wd:Q82059 wd:Q1930860 wd:Q846626 }
  ?item p:P414 ?st .
  ?st ps:P414 ?exch .
  ?st pq:P249 ?ticker .
  ?st wikibase:rank ?rank .
  ?sl schema:about ?item ;
      schema:isPartOf <https://en.wikipedia.org/> ;
      schema:name ?enwiki .
  OPTIONAL { ?st pq:P582 ?end . }
}
```

Exchange QIDs verified via `wbgetentities` 2026-08-17: `Q13677` New York Stock
Exchange, `Q82059` Nasdaq, `Q1930860` OTC Markets Group, `Q846626` NYSE American.

Measured: HTTP 200, 21.6 s, **4,015 rows**, 417 KB raw.

**Exchange scoping is a correctness requirement, not an optimization.** Measured
against the 420-ticker universe:

| Scope | Resolved | Ambiguous (>1 title) |
|---|---|---|
| Global | 270 (64.3%) | **41 (15.2%)** |
| US-scoped | 251 (59.8%) | **9 (3.6%)** |

Unscoped collisions are cross-domain and catastrophic: `BA` → Boeing / Bangkok Airways
/ Bell Aliant; `DTE` → DTE Energy / Deutsche Telekom; `RR` → Richtech Robotics /
Rolls-Royce; `COST` → Costco / Costain Group.

### 2.3 Two resolution rules

Applied in order, both measured against the 420-ticker universe:

1. **Drop `wikibase:DeprecatedRank` statements.** 15 ambiguous → 12. Fixes `AAL`, `GL`,
   `AMAT`.
2. **Drop statements whose `pq:P582` end-date is in the past — but only when a
   non-ended alternative exists for that ticker.** 12 → **9**. The proviso is
   load-bearing: without it, tickers whose *only* statement is historical resolve to
   nothing, and all 251 are preserved with it. Correctly yields `GOOG`/`GOOGL` →
   Alphabet Inc. (Google ended 2016-01-01), `GE` → GE Aerospace (General Electric
   ended 2024-04-02), and separates BBBY's two corporate eras.

The residual 9 are **same-company-family only** — `COHR`, `CPA`, `DELL`, `DOW`, `HTZ`,
`QQQ`, `SNOW`, `WB`, `WEN` (e.g. Dow Chemical vs. Dow Inc.). Worst case is a level
shift, never a category error. They go in the override file (§2.5).

Automatic tiebreaks were tested and **rejected**: ranking by sitelink count scores 4/9;
joining SEC CIK via P5531 scores 4/5 and introduces *new* errors (`SLS` → Galena
Biopharma, `SNOW` → Castor Maritime, `WBD`/`GE` stale). CIK is per-registrant and goes
stale across renames and mergers.

### 2.4 The truncation guard — mandatory

**WDQS silently truncates.** Measured 2026-08-17: a variant query returned **HTTP 200
at 60.19 s with 440 rows instead of 4,015** — no error, no truncation header — and was
served with `cache-control: public, max-age=300`, so the *partial* result is cached and
re-served (verified: immediate re-request returned the identical 440 rows in 0.16 s).

A truncated snapshot is indistinguishable from a healthy one by inspection. Therefore:

> **`fetch_ticker_map` MUST issue an independent `SELECT (COUNT(*) AS ?n)` over the same
> WHERE clause and refuse to overwrite the snapshot unless the row count matches.**

On mismatch: `degrade.warn("tickermap", "row count N != expected M — keeping snapshot")`
and serve the existing snapshot. This is the single most dangerous behavior found in
this research and it is invisible without the check.

Two further measured failure modes the fetcher must survive: **HTTP 504 at 65 s** when
a large `VALUES` list of tickers is inlined (filter locally instead — the unfiltered
bulk query is *faster* than the filtered one), and **HTTP 429** under rapid requests
(the existing `_get_json` exponential backoff covers this).

### 2.5 Override file — `radar/ticker_overrides.yml`

Curation is source, not state: it lives on `main` under review, not on the orphan
`data` branch which CI overwrites. ~32 entries, each with a one-line reason.

**9 disambiguation picks** (§2.3 residual).

**23 holding-company splits**, where Wikidata's ticker-bearing item legitimately has no
article sitelink because the corporate entity and the article are separate items:
`API`, `APP`, `CELH`, `CRCL`, `CRSR`, `CRWV`, `DC`, `FIG`, `GNS`, `KLAR`, `LITE`,
`MDA`, `MRAM`, `ONON`, `PYPL`, `QBTS`, `RDDT`, `RGTI`, `RKLB`, `SA`, `TH`, `UUUU`,
`WULF`. All 23 titles verified to exist via the Wikipedia API on 2026-08-17.

Overrides win over the snapshot unconditionally. An override naming a title that does
not exist is a test failure, not a runtime fallback (§4).

### 2.6 What `about.py` becomes

- Look up the exact title: override → snapshot → **nothing**.
- Fetch the summary **by exact title**. Delete the company-name path entirely.
- **Delete every fuzzy/opensearch fallback.** Measured, Wikipedia search returns
  `STEM` → Embryonic stem cell, `AMPX` → Yi Cui (scientist), `BATL` → 3rd Battalion,
  5th Marines, `MVIS` → Microvision (1979 game console). Fuzzy matching *is* the bug.
- Unmapped ticker ⇒ no description, and (in E2) no pageviews series. Render nothing.

### 2.7 Refresh and vendoring

Follows `radar/cramer.py`'s contract verbatim: live fetch → validate (§2.4) → vendor
snapshot → parse; on upstream failure serve the snapshot with a `degrade.warn`; when
both are gone return `{}` and warn. Snapshot `data/ticker_articles.json` rides the
orphan `data` branch.

Refreshed **inside the daily run, only when the snapshot is >30 days old**, fail-soft to
the existing snapshot on any error. No new workflow and no new secret surface. Listing
churn justifies it: new US listings carrying a P580 start-date ran 26/18/25/25 for
2022–2025 and 9 YTD 2026 — **~25/year against a ~3,500-ticker base, <1%/yr**.

Size is a non-issue: **3,779 pairs, 95 KB** — 11× smaller than the
`data/cramer_snapshot.json` (1.03 MB) already committed to that branch. Because the
snapshot covers the whole US universe, board churn never triggers a live lookup.

### 2.8 Cache migration

The live `data/about.json` holds ≥34 poisoned entries keyed by company name; they will
not self-heal, because the wrong entry is a cache *hit*. Add a `schema` key to the cache
file. On load, a cache whose schema does not match the current version is **discarded
wholesale** and repopulated. One-time cost: the next daily run re-fetches summaries for
the board only (`top_n: 15` plus the Still Running lane), not all 420.

## 3. Data contract

`data/ticker_articles.json` (vendored, data branch):

```json
{"schema": 1,
 "fetched": "2026-08-17",
 "rows_fetched": 4015,
 "rows_expected": 4015,
 "map": {"AAPL": "Apple Inc.", "TSLA": "Tesla, Inc.", "NVDA": "Nvidia"}}
```

Two counts, deliberately distinct — conflating them would defeat §2.4:

- `rows_expected` is the independent `SELECT (COUNT(*) …)` result; `rows_fetched` is the
  length of the result set actually returned. **The snapshot is only written when they
  match** (measured healthy value 2026-08-17: 4,015 = 4,015). Persisting both lets a
  later reader re-verify the file it was handed rather than trust it.
- `len(map)` is a *third*, smaller number — **3,779** — because §2.3's rules collapse
  multiple exchange/rank/era statements per ticker down to one title. Do not assert
  `len(map) == rows_fetched`; they are not the same quantity and a test that equates
  them will fail on the first legitimate refresh.

`radar/ticker_overrides.yml`:

```yaml
overrides:
  PYPL: {title: "PayPal", why: "P249 item Q135683211 'PayPal Holdings' has no sitelink"}
  DOW:  {title: "Dow Inc.", why: "same-family ambiguity vs Dow Chemical Company"}
```

`data/about.json` gains `"schema": 1` at the top level (§2.8).

Public surface of `radar/tickermap.py`:

- `parse_rows(raw) -> dict[str, str]` — pure, never raises, applies §2.3 rules.
- `load_overrides(path) -> dict[str, str]` — pure.
- `fetch_ticker_map(cfg, run_day) -> dict[str, str]` — fail-soft, warns, never raises.

## 4. Testing

Matching house style: `monkeypatch.setattr` on the module's private fetch helper, fixtures
under `tests/fixtures/`. **No live network** — the suite is hermetic as of `b6b90ad` and
must stay that way.

1. `parse_rows` applies the qualifier path and drops `DeprecatedRank`.
2. `parse_rows` drops a past-`P582` statement **only when a live alternative exists** —
   and keeps it when it is the sole statement. Both directions, since the proviso is
   what preserves all 251.
3. Overrides beat the snapshot.
4. **Every override title exists** — asserted against a committed fixture of verified
   titles, not a live call. A typo'd override is a wrong-entity bug of exactly the kind
   this spec exists to eliminate.
5. **Row-count mismatch refuses to overwrite the snapshot** and warns. The highest-value
   test here; §2.4's failure is silent by construction.
6. Upstream down ⇒ snapshot served + `degrade.warn`; both gone ⇒ `{}` + warn.
7. `about.describe` on an unmapped ticker returns no description and makes **no**
   network call — the anti-fuzzy guarantee, asserted as a call count of zero.
8. Cache with a stale `schema` is discarded, not merged.
9. Regression, table-driven over the §1 list: `AAPL`→`Apple Inc.`, `ADBE`→`Adobe Inc.`,
   `HTZ`→`Hertz Global Holdings`, `SDGR`→`Schrödinger, Inc.`, `ID`→∅, `MVIS`→∅.

## 5. Risks

| Risk | Mitigation |
|---|---|
| **Silent WDQS truncation** vendored as truth | §2.4 `COUNT(*)` guard; `rows` persisted in the snapshot for re-checking |
| WDQS 504/429/outage | Snapshot fallback + existing backoff; refresh is monthly, so an outage is a non-event |
| Wikidata vandalism → wrong title | Same-family worst case after §2.3; snapshot only advances when the count validates, so a bad refresh is at most one month of one ticker |
| Override file rots as companies rename | Test 4 pins existence; ~32 entries is small enough to eyeball at review |
| Coverage looks like it barely moved (59.3%→59.8%) | Expected and correct — **the win is precision, 13.7%→0.4% wrong.** On the actual *equity* universe (330 of 420; the rest are 53 ETFs and 23 crypto that structurally cannot carry an exchange ticker statement) coverage is **73.3%, rising to 80.3% with overrides** |
| Micro-caps still unmapped | ~65 have no English Wikipedia article at all (verified for AAOI, CIFR, CLSK, ONDS, POET, NVTS…). Unreachable by any strategy. They render nothing — which is the correct outcome, not a gap to paper over |

## 6. Out of scope

- **The P355/P1830/P1889/P1056 holding-company bridge.** Tested: 4 of 21 produce any
  candidate and the candidates are garbage — `PYPL` → BlackRock / S&P 500 / Venmo,
  `RDDT` → Condé Nast / Alien Blue, `ONON` → Sneakers. It reintroduces the exact
  wrong-entity class this spec removes. Do not build it.
- **CIK/P5531 as a primary join** — 40.7% coverage, adds 5 tickers, introduces new
  errors (§2.3). Viable later as a *secondary* tiebreak for the 9; not needed now.
- Non-US listings, ETF constituents, crypto symbols.
- The pageviews ingest itself — that is E2, and it consumes this map.
