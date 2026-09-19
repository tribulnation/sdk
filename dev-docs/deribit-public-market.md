# Deribit public Market qualification

Scope: [SDK #33](https://github.com/tribulnation/sdk/issues/33), Deribit only.
Implemented and probed on mainnet on 2026-09-19. Public Market support requires
Deribit 0.3.0 and SDK 2.2.0, separate from Terminal collection/serving rollout.
[ADR 0021](adr/0021-deribit-public-market.md) records the supported subset.

## Capability handoff

| Surface | Implemented scope | Native mapping |
| --- | --- | --- |
| Discovery | Active spot and linear perpetuals with quote=settlement | `get_instruments`, explicit product metadata |
| Tickers | All discovered or selected instruments | Product-scoped `get_book_summary_by_currency` |
| REST depth | 1–100 levels, default 20 | `get_order_book`, native base quantities |
| Depth stream | 1–20 levels, default 20 | Shared `book_grouped`, `100ms`, full snapshots |
| Trade candles | Native spot and linear perpetuals; four intraday intervals | `get_tradingview_chart_data`, `transport='ws'` |
| Index/statistics | Native index, mark, optional base open interest | `ticker`, paced shared requests |
| Rules/account fees | Unsupported | Fee denomination and quantity-step fallback unqualified |
| Scheduled funding | Unsupported | Continuous accrual does not establish SDK payment-time semantics |
| Private Market/trading | Unsupported | Explicit `NotImplementedError` |
| Wallet | Existing full declared public metadata | Currency/network data, currency-level fees/confirmations |
| Earn | Existing partial public `instruments` | Seven-day SMA APRs; no subscription/eligibility guarantee |
| Report | Existing partial private `history`/`snapshot` | Cash balances/positions; ambiguous ledger rows retained |

`MarketSDK()` now has a credential-free mainnet Deribit default. Private credential
settings are not resolved by this adapter; testnet Market accounts are rejected.
Exchange IDs are `spot` and `perp`. Reference IDs are
`deribit:spot:BTC_USDT` and `deribit:perp:BTC_USDC-PERPETUAL`; native spelling is
preserved. Discovery found **19 spot and 126 linear perpetuals**. Inverse contracts,
dated futures, options and combinations are excluded. Native product metadata can
include tokenized/RWA instruments; discovery is not a crypto-only promise.

Books, volume and linear open interest already use base units. Do not multiply them
by contract size. Ticker summaries have no top-of-book sizes, so those optional SDK
fields remain unset. Statistics do not populate funding estimates. See the
[linear specification](https://support.deribit.com/hc/en-us/articles/31424969384605-Linear-Perpetual)
and [quantity-field guidance](https://support.deribit.com/hc/en-us/articles/38507223482781-API-guidance).

## Candle bounds and history

Supported intervals are `1m`, `5m`, `15m`, `1h`. `4h` is absent from the native
resolution enum. Native `1D` candles were observed opening at **08:00 UTC**, not the
SDK's current epoch-aligned daily grid; daily support needs a separate contract
extension. Both unsupported intervals fail before making a request.

Coinbase-routed spot instruments expose an empty `CANDLE_INTERVALS`, based on typed
`is_csr`/`is_cbe_routed` metadata. Routed `BTC_USDC` still serves books/tickers;
`BTC_USDT` qualified native candles. Routing is a metadata snapshot cached within
an owner; construct a fresh venue to refresh discovery/routing. There is no static
routed-pair list or Coinbase candle fallback.
[Routing documentation](https://docs.deribit.com/articles/spot-trading-venues).

Candle requests use validated native WebSocket calls: HTTP returned JSON-RPC
`-32601 Method not found` for BTC_USDT and both BTC/ETH linear perpetuals, while
WebSocket calls returned validated candles. Requests use bounded **1000-open windows**,
not a claim about the venue's absolute maximum. SDK bounds remain aware and half-open,
including submillisecond bounds; wire timestamps are milliseconds. Malformed parallel
arrays fail visibly. Empty windows do not terminate traversal. Optional base volume
and quote turnover stay unknown when absent.
[Candle API](https://docs.deribit.com/api-reference/market-data/public-get_tradingview_chart_data).

The public PoC qualified **1,002 unique, aligned candles across two pages** for each
supported interval on BTC_USDT, BTC_USDC-PERPETUAL and ETH_USDC-PERPETUAL. January 2
2023 and 2025 three-hour minute windows returned 180 BTC linear candles. BTC_USDT's
2025 window returned 180; its 2020/2023 windows and the BTC linear 2020 window were
empty. These are dated observations, not retention cutoffs or archive completeness.

## Funding and typed-client findings

Seven-day BTC/ETH linear funding requests each returned 168 hourly observations.
The native fields include `interest_1h`, `interest_8h` and timestamps. The SDK requires
payment-time semantics; continuous accrual and daily cash settlement do not justify
mapping hourly observations to invented hourly payments. `funding_rates`,
`next_funding` and funding statistics remain unsupported. A future extension must
settle the period/time contract and verify open-start and page-boundary behavior.

Broad BTC summaries failed typed validation because `estimated_delivery_price` was
null in 76 records. The exact instrument condition remains unverified. The package
requests its supported spot/futures kinds; those responses validated, including all
145 supported ticker IDs. The defect and reproduction cell are recorded in
[typed-client-issues.md](../typed-client-issues.md). No validation was disabled.

## Qualification and Catalogue boundary

The [public PoC](../packages/impl/deribit/poc/market/public.py) independently checks
discovery, all ticker/statistic IDs, books, streams, cross-page intervals, historical
samples and Catalogue gaps. Paired output is local and gitignored. One real snapshot
qualifies each stream; an illiquid book need not produce additional updates on demand.
The obsolete mixed mainnet/testnet Market prototype has been retired.

Deterministic regressions cover product exclusions, routed candle restrictions,
native units, unknown values, fractional bounds, sparse pages, malformed arrays,
page-level retries, shared stream acquisition/cleanup and subscriber mutation isolation.
All **897 offline tests** passed, including **27 Deribit tests**. Type checks, lint,
generated documentation checks and all five Deribit PoC type/lint checks passed.
The new public PoC has executed outputs for its 13 selected cells; the other four
historical PoCs were checked statically, not re-executed against private accounts.
The public SDK conformance run passed **20 checks**, with **37 explicit skips**:
29 unrelated Bitget cases, four perpetual-only checks on spot and four declared
unsupported rules/funding checks. These skips are not verification.

The fingerprinted consistency run against the sibling Catalogue passed its current
policy (**23 checks**) and offline verifier. It contains no failed checks, but that
Catalogue has **zero Deribit spot/perpetual mappings**. The PoC lists all 19 spot and
126 perpetual IDs as missing canonical market translations, plus missing asset IDs.
Consistency success therefore does not certify canonical identities or exhaustive
coverage. Catalogue additions are required for Terminal and remain separate work;
no SDK symbols were renamed to hide the gaps.

## Version and release handoff

Initial implementation qualification used typed-deribit **0.3.0**, editable
tribulnation-deribit **0.2.1** and core SDK **2.1.0**, with the new source changes.
The release pair is **tribulnation-sdk 2.2.0** and
**tribulnation-deribit 0.3.0**. Deribit's SDK floor is 2.2.0 and the core Deribit
extra requires 0.3.0. Final candidate qualification is recorded separately in
`release-evidence/`. The SDK release PR carries the integration with Deribit
metadata still at 0.2.1; the follow-up Deribit release raises its version and floor.
Both branches recorded matching Deribit reports. Deribit 0.3.0 was published
after its release gate passed; the initial SDK publication was blocked by Bit2Me.
The SDK release completes the dependency pair with fresh all-venue evidence under
[ADR 0022](adr/0022-bit2me-one-sided-ticker-limitation.md).

[PR #25](https://github.com/tribulnation/sdk/pull/25) already merged the earlier
Wallet/Earn/Report release; this work does not recreate it. Public Market qualification
does not replace full release read-surface qualification. The existing mainnet
Wallet/Earn plus testnet Report allowance in [ADR 0012](adr/0012-deribit-public-mainnet-private-testnet.md)
does not allow testnet Market evidence or certify private mainnet behavior.

Before Terminal rollout, hand off published versions, Catalogue revision/mappings,
exact exchange/native IDs, four supported candle intervals and explicit funding,
rules, daily, inverse and routed-spot limits. Publication, archive ingestion and
Terminal serving are separate actions. Kraken/KuCoin work under #33 remains separate.

## Reproducing public checks

```sh
.venv/bin/sdk-dev poc run packages/impl/deribit/poc/market/public.py --cells 1-6,9,20,22,28-31 --timeout 180
.venv/bin/sdk-dev poc check deribit
.venv/bin/pytest packages/impl/deribit/test -q
.venv/bin/sdk-dev test market deribit --accounts /tmp/deribit-public-accounts.toml
.venv/bin/sdk-dev test consistency deribit --catalogue ../catalogue/data --output /tmp/deribit-public-consistency-new
.venv/bin/sdk-dev results verify /tmp/deribit-public-consistency-new --catalogue ../catalogue/data
.venv/bin/sdk-dev catalogue check
.venv/bin/sdk-dev docs check
```

The public accounts file contains only `[accounts]`, selecting credential-free defaults.
Use a new output directory for every fingerprinted run.
