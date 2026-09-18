# KuCoin public Market qualification

Scope: [SDK #33](https://github.com/tribulnation/sdk/issues/33), KuCoin only.
This is an unreleased public-data expansion, separate from the existing Classic
spot-side Wallet/Earn/Report package and Terminal's collection/serving rollout.

## Capability handoff

| Surface | Scope | Native mapping |
| --- | --- | --- |
| Discovery | Enabled spot; open linear perpetuals | `spot.all_symbols`, `futures.all_symbols` |
| Tickers | Spot and linear perpetuals; explicit selection or all discovered markets | `spot.all_tickers`, `futures.all_tickers`; futures metadata supplies base 24h volume |
| Rules | Public constraints; unknown standard fees | Symbol metadata; no account fee reads |
| Depth | REST 1–100 levels, default 20 | Public partial books, 20/100 native levels |
| Depth stream | 1–5 levels, default 5 | Public five-level snapshots, shared upstream and bounded SDK subscriber queues |
| Candles | Trade-price OHLCV; six SDK intervals | Classic spot/futures klines, explicit time windows |
| Index | Linear perpetuals | Published contract `indexPrice` |
| Next funding | Linear perpetuals | Dedicated `current_funding_rate`: `value`, `fundingTime`, `granularity` |
| Funding history | Settled public rates; inclusive bounds | Typed backwards pager, retry per page; open start means earliest available |
| Perpetual statistics | Index, mark, base-unit open interest | Contract metadata; optional funding fields remain unset; use `next_funding` |
| Private Market methods | Unsupported | Explicit `NotImplementedError`; private reporting stays on Report |

Exchange IDs are `spot` and `perp`. Spot matches existing Catalogue metadata.
Catalogue PR [#137](https://github.com/tribulnation/catalogue/pull/137) adds the missing
`exchange: perp` to all 183 existing KuCoin perpetual entries. Strict consistency
passes against that candidate; release qualification must use the merged Catalogue.
Full reference IDs are `kucoin:spot:BTC-USDT` and `kucoin:perp:XBTUSDTM`.
Unknown exchange IDs and inverse/dated/otherwise unsupported contract IDs are rejected.
Native asset and symbol spellings are preserved; canonical translation belongs to Catalogue.

Linear perpetual book/ticker quantities, constraints, candle volume and open interest
are multiplied by the venue's contract `multiplier` to produce SDK base units.
The contract's `volumeOf24h` is already in base units and is not multiplied again.
Only positive-multiplier, non-inverse contracts with no expiry and equal quote/settlement
currencies are included. Standard fees remain unknown because combined public fee
semantics were not qualified. No account permissions are needed by Market.

## Candle and funding bounds

SDK intervals: `1m`, `5m`, `15m`, `1h`, `4h`, `1d`. Unsupported intervals fail before
requesting data. Candles require timezone-aware `[start, end)` bounds, preserve native
ordering, and never synthesize rows for periods absent from the API. Fractional bounds
are converted to the final representable inclusive wire timestamp below `end`.
Spot requests use seconds; futures requests use milliseconds. Spot tuple ordering is
open/close/high/low; futures ordering is open/high/low/close.

On 2026-09-18, Classic spot returned 1,500 rows per full window. Classic futures
returned only 200 rows from requested 500-candle windows, despite its
[documentation claiming 500](https://www.kucoin.com/docs-new/rest/futures-trading/market-data/get-klines).
The installed typed client's pager already uses 200. The SDK uses bounded time windows
of 1,500/200, and advances even after a sparse or empty window. A short response is not
an end-of-history signal. [Spot documentation](https://www.kucoin.com/docs-new/rest/spot-trading/market-data/get-klines)
also explicitly permits absent intervals.

Public funding has inclusive bounds and a different pager. An omitted start uses
Unix epoch as the lower request bound, preserving the SDK's earliest-available meaning;
it is not replaced with a recent seven-day window. The typed pager removes repeated
boundary settlements. An omitted end is resolved to the current UTC time.

## Live observations, 2026-09-18

The credential-free [PoC](../packages/impl/kucoin/poc/market/public.py) validates typed
responses throughout. Its paired notebook is local and gitignored.

- Discovery, public tickers/rules, 20/100-level depth, five-level spot/perpetual streams,
  index, next funding, statistics and funding history returned real data.
- BTC and ETH spot returned 1,502 candles across the 1,500-row boundary for every SDK
  interval, without gaps or duplicate opens in the sampled windows.
- BTC and ETH perpetuals crossed 200-row boundaries for every SDK interval. Some
  one-minute rows were absent; re-querying sampled absent rows individually also
  returned nothing. No missing rows were fabricated.
- BTC spot minute/daily windows on January 2 of 2020, 2024 and 2025 returned data.
- XBTUSDTM's January 2024 minute window was empty while daily candles were present;
  January 2025 minute/daily windows returned data. The sampled January 2020 windows
  were empty. These observations do not establish a universal retention cutoff or
  a complete archive for any product.
- Open-start XBTUSDTM funding walked 72 pages and 7,103 unique settlements, from
  2020-03-26 12:00 UTC through 2026-09-18 16:00 UTC.
- No typed-response validation failures were found in these probes. The 500-versus-200
  cap is a documentation discrepancy, not a reason to bypass client validation.

## Qualification and release boundary

The implementation includes deterministic tests for exact IDs, contract exclusions,
quantity units, sparse pages, fractional bounds, page-level retry, funding overlap,
and shared WebSocket acquisition/cleanup. The SDK live suite has both spot and
perpetual reference cases, including cross-page candles. All 33 required read checks
passed (24 public Market checks and nine Wallet/Earn/Report snapshot checks), with
four perpetual-only methods excluded on the spot reference. Public PoC execution
passed all 19 selected cells. Type checks, lint and generated documentation checks
also passed. The rebased full offline suite passed 867 tests. Strict Catalogue consistency
passes against Catalogue PR #137; publication still requires current release evidence.

The source checkout still carries `tribulnation-kucoin 0.2.1` and core SDK `2.0.2`
metadata; those released version numbers must not be advertised as containing this
expansion. Proposed handoff versions are KuCoin `0.3.0` and SDK `2.1.0`, subject to the
normal release work. The core release must include the MarketSDK registration; KuCoin
should then declare that released SDK floor. Qualification here uses typed-kucoin
`0.3.0`; no typed-client release is required by the tested mappings.

Before publication, record matching passing `surfaces` and `consistency` evidence for
the final release versions and dependencies. Existing release evidence predates this
capability change and is insufficient. The earlier
[KuCoin release PR #30](https://github.com/tribulnation/sdk/pull/30) is already merged;
this work does not recreate its publication or change its private reporting scope.

Terminal should consume only the qualified product/method/interval combinations after
its separately approved rollout. Catalogue coverage gaps remain explicit: new venue
symbols do not automatically acquire canonical asset mappings, and omitted inactive
or excluded contracts are not evidence of zero activity.

## Catalogue handoff

Catalogue [PR #137](https://github.com/tribulnation/catalogue/pull/137) fixes all 183
missing perpetual exchange identities. Strict KuCoin consistency passes its coverage
policy against that candidate, including exchange/market identities, ticker/stat
selection and sampled ticker/depth comparisons. Nineteen existing entries remain
outside supported discovery: five active inverse/dated contracts and fourteen absent
from current public listings. Absence alone is not treated as delisting.

The PoC additionally found 689 active spot IDs and 505 supported perpetual IDs without
Catalogue entries. BTC/ETH reference markets are already mapped. New symbol mappings
remain a separate coverage task; consistency does not establish exhaustive coverage.

Merge Catalogue first, then capture final-version release evidence against the merged
data. Core SDK publication requires every supported venue's read reports and applicable
Market consistency reports; the existing reports do not match this changed candidate.
Do not waive that gate or infer publication readiness from KuCoin-only qualification.
