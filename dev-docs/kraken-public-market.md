# Kraken public Market qualification and remaining scope

Scope: [SDK #33](https://github.com/tribulnation/sdk/issues/33), Kraken only.
This records live-qualified Spot coverage and the new public linear perpetual
implementation. Archive ingestion remains separate. KuCoin's independent work is
recorded in [its handoff](kucoin-public-market.md).

## Capability handoff

| Surface | SDK coverage | Qualification boundary |
| --- | --- | --- |
| Discovery, tickers, rules | Spot and qualified linear perpetuals | Public metadata and native market IDs; Futures standard fee rates unknown |
| Depth | Spot REST/streams; perpetual REST | Futures full books sorted before trimming to requested levels |
| Candles | Spot and perpetuals, all six SDK intervals | Recent retained Spot data; bounded Futures trade-chart requests |
| Index, perpetual statistics | Qualified perpetuals | Native index/mark price, base open interest; funding estimate left unset |
| Funding history | Qualified perpetuals | Native relative rate; period start + one hour becomes SDK settlement time |
| Next funding, Futures streams | Unsupported | Native next-rate/time and subscription mappings are not qualified |
| Private Futures and trading | Unsupported | Outside this public implementation |
| Wallet/Earn/Report, private Spot reads | Existing support, not requalified here | Credentialed surfaces retain their existing limitations |

Exchange IDs are `spot` and `perp`. Full references include `kraken:spot:XBTUSD`
and `kraken:perp:PF_XBTUSD`. Spot REST altnames remain market IDs; internal response
keys and WebSocket symbols are joined internally. Futures IDs are exact native
instrument symbols. Assets remain internal Kraken IDs such as `XXBT`, `XETH`, `ZUSD`;
canonical translation belongs to Catalogue. See [ADR 0020](adr/0020-kraken-public-perpetuals.md).

## Spot candle contract and typed responses

The released `typed-kraken 0.4.0` declares `OhlcResult` as a dictionary whose values
are an integer cursor or lists of eight-element tuples. Tuple time validates to an
aware `datetime`, prices/VWAP/volume to `Decimal`, and trade count to `int`.
The former description that only `last` was declared is stale. Live probes use
validation throughout and select the pair's internal key, never the first dictionary
value. The SDK rejects a missing pair or a cursor in place of its rows.

Candles require aware `[start, end)` bounds and select by candle open. Equal bounds
return no rows without a request; reversed or naive bounds fail locally. The SDK
requests `since = start - interval`, filters to the requested bounds, removes repeated
opens and preserves response order. It includes a still-forming candle if its open
falls inside the range; consumers needing only closed candles must bound `end` at
the current interval's open. Missing history returns an empty or partial result, not
an archive-completeness assertion.

| SDK interval | Wire minutes | Nominal 720-interval span |
| --- | --- | --- |
| `1m` | 1 | 12 hours |
| `5m` | 5 | 60 hours |
| `15m` | 15 | 7.5 days |
| `1h` | 60 | 30 days |
| `4h` | 240 | 120 days |
| `1d` | 1440 | 720 days |

Other Kraken intervals are outside the SDK candle contract. Kraken documents at most
720 recent rows and an always-present forming candle; `since` cannot recover older
history. These nominal spans are planning limits, not promises of complete rows for
every market. [OHLC documentation](https://docs.kraken.com/api-reference/market-data/get-ohlc-data).

## Live candle observations, 2026-09-19

BTC (`XBTUSD`) and ETH (`ETHUSD`) each returned **721 typed rows** for every SDK
interval when `since` was 1,000 intervals earlier. Their opens spanned 720 intervals,
including the current interval. This differs from the documented 720-row count;
the SDK does not truncate to a hard-coded row cap or invent an older-history pager.
Minute samples began around 02:11–02:12 UTC and ended around 14:11–14:12 UTC;
daily samples began on 2024-09-29 and ended on 2026-09-19.

For all twelve market/interval combinations, the SDK returned three recent closed
candles and zero rows for a three-candle window 1,000 intervals earlier. Recent
opens were unique, aligned and within half-open bounds, and OHLC values were
consistent. Both hourly reference probes returned two rows after moving the lower
bound one microsecond beyond the first open, one forming row when requested, and
zero rows for equal bounds. No typed-response validation failures were observed.

These observations qualify the sampled retained windows, not complete history or
all listed pairs. The full measurements are in PoC cells 23–25.

## Archive backfill is a separate task

Kraken's downloadable OHLCVT files cover historical Spot candles. On 2026-09-19,
the archive page advertised coverage through **2026-06-30**, split into several large
parts, and stated that no-trade intervals are absent. This pass inspected the archive
metadata, not the files. [Archive documentation](https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data).

An archive import followed by a recent REST call does not necessarily bridge the
publication lag: minute candles retain roughly half a day while the advertised
archive ends months earlier. Any collector must record that gap explicitly.

Concrete backfill work:

1. Build a separate file-ingestion path with a manifest recording source URLs,
   checksums, archive cutoff, per-file interval, and observed first/last opens.
2. Inspect actual CSV schemas and filename IDs, join them to Kraken-native SDK IDs
   using venue metadata, and report unresolved or historical/delisted pairs. Do not
   guess that a filename uses REST altnames or rename SDK IDs to match it.
3. Preserve sparse periods; deduplicate archive/API overlap by native market,
   interval and open time. Define replacement of mutable forming rows before rollout.
4. Measure the archive-to-REST gap for each interval. Qualify an additional historical
   source or ongoing collection where needed; incomplete ranges remain visible.

These are ingestion tasks, not an extension of the OHLC `since` cursor. Their owner
and deployment belong to Terminal's separately approved collection work.

## Public Futures implementation and live observations, 2026-09-19

The missing public endpoints tracked in [typed-dev #221](https://github.com/tribulnation/typed-dev/issues/221)
shipped in `typed-kraken 0.4.0` through [typed #129](https://github.com/tribulnation/typed/pull/129).
The SDK dependency floor is now `>=0.4.0`. All formerly blocked cells were rerun
against the release and actual SDK methods before removing the typed-client issue.

Discovery joins instruments with market tickers and requires `flexible_futures`,
`tradfi == False`, USD quote, unit contract size, tradeable/unexpired metadata, no
`lastTradingTime`, a perpetual ticker tag and an unsuspended ticker. This returned
**271 instruments** from 296 instrument records. The API's non-`tradfi` class includes
some tokenized equities and commodities; this is not a crypto-only filter. Inverse,
dated, expired, suspended and non-unit products remain outside this qualification.
No symbol-prefix heuristic or canonical asset rename is used.

| Native reference | Quantity step/minimum (base) | Price tick (USD) |
| --- | --- | --- |
| `PF_XBTUSD` | `0.0001` | `1` |
| `PF_ETHUSD` | `0.001` | `0.1` |
| `PF_BONKUSD` | `1000` | `0.000000001` |

For unit-size linear products, book/ticker quantities, trade-candle volume and open
interest are native base quantities. Rules use `10 ** -contractValueTradePrecision`
and `tickSize`. `maxPositionSize` is not an order-size maximum, so `max_qty` stays
unknown. USD fee identity resolves through Assets to native `ZUSD`; standard fee
rates remain unknown. Full REST books are sorted before SDK level trimming because
live bids arrived in ascending order. Index and mark prices use their native ticker
fields. Absolute ticker funding figures are not divided by mark price to manufacture
a relative estimate. [Instrument metadata](https://docs.kraken.com/api-reference/instrument-details/get-instruments),
[tickers](https://docs.kraken.com/api-reference/market-data/get-tickers),
[linear contract specifications](https://support.kraken.com/in/articles/4844359082772-linear-multi-collateral-derivatives-contract-specifications).

### Futures candles

The SDK requests `trade` charts in bounded windows of at most 2,000 possible candle
opens. This is a tested request size, not an asserted venue maximum. Each request
uses the SDK exception/retry seam independently. Kraken's wire bounds are inclusive
seconds; the SDK converts the upper bound and filters validated candle opens to aware
`[start, end)` bounds. Response timestamps validate from milliseconds and OHLC/volume
from decimal strings. Empty windows advance normally; duplicates are removed within
a window, venue order is retained and an unexpected `more_candles` flag fails visibly.
The implementation does not depend on automatic typed-client chart pagination.

BTC and ETH passed all six intervals (`1m`, `5m`, `15m`, `1h`, `4h`, `1d`). Each also
returned **2,050 unique hourly opens in pages of 2,000 and 50**, with complete measured
coverage. Fractional lower bounds excluded the preceding open; forming rows were
included when in range; equal bounds made no request. A prelisting 2020 window was
empty, while BTC's 2023-01-01 through 2023-01-03 hourly window returned 48 rows.
These samples do not promise history since launch or fill no-trade intervals.
[Chart candles](https://docs.kraken.com/api-reference/candles/market-candles).

### Funding timestamp conversion

Historical funding maps `relativeFundingRate` directly. Kraken's timestamp marks the
start of the accrual hour; SDK `FundingRate.time` means settlement time. As approved,
the SDK adds **one hour**, then applies inclusive optional bounds to that converted
time. For example, a Kraken period starting at `08:00 UTC` maps to SDK settlement at
`09:00 UTC`. This conversion is documented in the implementation, public reference
and ADR, and covered by regression fixtures and live boundary probes.

The endpoint accepts only a symbol and returns its available history. Omitting
`start` preserves all returned rows. Both BTC and ETH returned **8,808 rows**, mapping
to settlements from `2025-09-17 09:00 UTC` through `2026-09-19 16:00 UTC` in this probe.
The latest row may therefore map to an hour-end still in the future; the SDK does
not silently discard it. Three-row inclusive windows passed on both references.
There is no claim of complete history since launch. `next_funding` and funding
estimates in perpetual statistics remain unsupported/unset.
[Funding history](https://docs.kraken.com/api-reference/historical-funding-rates/historical-funding-rates),
[hourly settlement specification](https://support.kraken.com/in/articles/4844359082772-linear-multi-collateral-derivatives-contract-specifications).

## Public discovery and Catalogue observations, 2026-09-19

The credential-free [PoC](../packages/impl/kraken/poc/market/public.py) returned
1,450 discovered Spot altnames and 1,450 ticker entries. `XBTUSD` and `ETHUSD`
returned public rules, 5/100-level REST books and three five-level streamed books
each. Responses were validated by the installed typed client throughout.

The PoC Catalogue cell found 914 discovered Spot IDs and 634 base/quote asset IDs
without translations in the sibling Catalogue checkout loaded by the repository
qualification tools. BTC/ETH reference market IDs
were mapped, but the native quote asset `ZUSD` was among the asset gaps. The full
missing-ID lists are in the local, gitignored paired notebook. This broad coverage
check is not the strict consistency/release suite; gaps are Catalogue additions,
not reasons to change Kraken's native SDK IDs.

The [Futures PoC](../packages/impl/kraken/poc/market/futures.py) additionally found
131 qualified perpetual IDs and native fee asset `ZUSD` without Catalogue
translations. BTC, ETH and BONK reference contracts already map to exchange `perp`.
Catalogue expansion is a separate change; missing translations do not alter SDK IDs.

The recorded consistency run passed the current coverage policy and its offline
verifier. It checked both exchanges, including the formerly excluded Kraken `perp`
exchange. Its 1,373 checks passed and 10 Catalogue coverage checks were explicitly
deferred by existing policy. This policy result is distinct from the broader PoC
missing-ID inventory above.

## Version and Terminal boundary

Verification uses published `typed-kraken 0.4.0`, editable `tribulnation-kraken 0.3.0`
and editable core SDK `2.1.0`. Declared floors are SDK `>=2.0.2` and typed client
`>=0.4.0`. Kraken `0.3.0` is the release candidate; publication awaits the release PR merge. The minimum SDK version was not separately
retested.

Terminal can use the new public perpetual surface after SDK publication and its own
lock, Catalogue, collection and serving review. Spot archive backfill remains a
separate ingestion task. Existing SDK PR #29 is merged and must not be recreated.
Public conformance and consistency evidence do not replace the repository's full
read-surface qualification required for a release. The release preparation additionally requalified all required read-only surfaces,
including Wallet, Earn and Report snapshots. No trading or transfers were performed.

## Reproducing the checks

```sh
.venv/bin/sdk-dev poc run packages/impl/kraken/poc/market/futures.py --cells 1-4,6-7,9,20,22-23,28-30 --timeout 300
.venv/bin/sdk-dev poc run packages/impl/kraken/poc/market.py --cells 13-19 --timeout 120
.venv/bin/sdk-dev poc run packages/impl/kraken/poc/market/public.py --cells 1,26-27 --timeout 120
.venv/bin/sdk-dev poc check kraken
.venv/bin/pytest packages/impl/kraken/test packages/sdk-dev/test/test_read_evidence.py packages/sdk-dev/test/test_consistency.py -q
.venv/bin/sdk-dev test market kraken --accounts /tmp/kraken-public-accounts.toml
.venv/bin/sdk-dev test consistency kraken --catalogue ../catalogue/data --output /tmp/kraken-futures-consistency
.venv/bin/sdk-dev results verify /tmp/kraken-futures-consistency --catalogue ../catalogue/data
.venv/bin/sdk-dev catalogue check
.venv/bin/sdk-dev docs check
```

The public account file contains only `[accounts]`, selecting the credential-free
Kraken default. The PoCs select public cells; private and state-changing cells carry
explicit nonexecution reasons. Paired notebooks contain measured outputs locally
and are gitignored. Earlier Spot qualification is in public PoC cells 1–7, 9 and
21–25; those include paced, bounded retries after initial public rate-limit failures.

The combined offline regression suite passed **138 tests**, including 15 new
perpetual tests. Public live conformance passed **21 tests with 36 explicit skips**
(irrelevant account/product cases and declared unsupported methods). All six Kraken
PoC scripts passed checks, with the selected public cells executed. Type checking,
lint, documentation generation checks and Catalogue ID-form checks passed. Matching
consistency evidence is recorded locally at `/tmp/kraken-futures-consistency` and
passed `results verify`; it is not a published release attestation.

## Release preparation

The `release/kraken` candidate targets `tribulnation-kraken 0.3.0`. Fresh read-suite
and consistency reports are committed under `release-evidence/kraken/`, recorded
against Catalogue main `b5b0338`. The release verifier passes for this candidate.
The read-suite report covers public Market plus Wallet, Earn and Report snapshots;
unsupported methods remain explicit exclusions. The full offline suite passed
**882 tests**, and both the source distribution and wheel built successfully.

The SDK-owned docs are synchronized to the landing `dev` branch for review,
including the Kraken capability page, generated method examples and support matrix.
Publication awaits the release PR merge; the docs merge to landing `main` follows
that review and merge separately.
