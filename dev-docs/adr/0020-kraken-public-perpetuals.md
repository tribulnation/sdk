# ADR 0020: Kraken public linear perpetual Market support

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; implementation and release qualification are separate.
2. Date: 2026-09-19

## Context

SDK #33 separates public market capabilities from existing private Wallet/Earn/Report
support. Released typed-kraken 0.4.0 now exposes public Futures REST and Charts.
The Catalogue already identifies Kraken perpetuals with exchange `perp` and native
symbols such as `PF_XBTUSD`; blanket exclusion of that product is no longer appropriate.

## Decision

1. Add `kraken:perp:<native symbol>` alongside unchanged Spot identities. Discover
   `flexible_futures` instruments with USD quote, unit contract size, `tradeable=true`,
   `isExpired=false`, no `lastTradingTime`, and `tradfi=false`, joined to an unsuspended
   ticker tagged `perpetual`. These are API classifications, not a crypto-only promise:
   some tokenized assets are marked non-tradfi. Inverse, dated, expired, suspended,
   non-unit and explicitly tradfi products are outside this implementation.
2. Preserve native base-unit book quantities, ticker sizes, volume and open interest.
   Quantity step is `10 ** -contractValueTradePrecision`, including negative precision.
   Sort the entire book before trimming. Do not use maximum position size as an order cap.
3. Public rules identify USD fees through Kraken Assets as `ZUSD`. Standard fee rates
   and maximum order size remain unknown. Private Futures methods, account fees,
   trading and Futures WebSocket subscriptions remain unsupported.
4. Expose all six SDK trade-candle intervals through the `trade` chart type. Use bounded
   2000-open time windows, inclusive wire bounds and aware half-open SDK filtering.
   Continue after empty windows, preserve native row order, remove duplicate opens,
   and retry each request independently. Unexpected truncation fails visibly.
   Retained API history is not a complete archive guarantee.
5. Historical funding uses native `relativeFundingRate`. Kraken's timestamp identifies
   the start of an accrual period, while SDK `FundingRate.time` means payment time.
   Map settlement to **native timestamp + one hour**, as approved for this extension,
   then apply inclusive bounds. An omitted start preserves all returned history.
   The most recent row can describe a period whose settlement is still upcoming.
6. Keep `next_funding` unsupported and optional funding statistics unset. A current
   absolute ticker rate divided by today's price does not recover the published
   relative rate, and a locally inferred next timestamp is not a qualified forecast.

## Alternatives considered

- Classify contracts from symbol prefixes: unnecessary because native product fields
  and ticker tags identify their type directly.
- Reuse the Spot retention limit for Futures: live Charts probes returned 2050 hourly
  rows across two pages and January 2023 data.
- Copy the native funding period start into SDK payment time: shifts the meaning by
  one hour. The user explicitly approved the documented hour-end conversion.
- Use the typed automatic chart pager: it is not exposed because its shared seek
  converter cannot yet handle raw millisecond cursors with second request bounds.
  Explicit page requests implement the SDK's own bounded window contract.

## Consequences

The existing public account can read both products without Futures credentials. The
native Catalogue mappings for reference contracts already use `exchange: perp`;
missing instruments and `ZUSD` translation remain visible Catalogue gaps. New reference
cases exercise the perpetual implementation, and consistency no longer blanket-excludes
Kraken perpetuals. SDK publication and Terminal collection remain separate actions.

References:

- [Instrument definitions](https://docs.kraken.com/api-reference/instrument-details/get-instruments)
- [Linear contract units and hourly funding](https://support.kraken.com/in/articles/4844359082772-linear-multi-collateral-derivatives-contract-specifications)
- [USD fee denomination](https://support.kraken.com/in/articles/360048917612-fee-schedule)
- [Qualification handoff](../kraken-public-market.md)
