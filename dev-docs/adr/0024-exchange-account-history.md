# ADR 0024: Exchange-wide personal trade and funding history

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted
2. Date: 2026-09-22

## Context

Exchange history methods currently require a single market. Consumers needing
account history must repeat queries, even when the venue already returns all
markets. Enumerating the current catalogue misses delisted markets and can repeat
an account-wide request once for every instrument.

## Decision

Extend `Exchange.trades_history` and `PerpExchange.funding_payments` to accept
`None` as the positional market selector. Existing string-selector calls keep
their market delegation and record shapes. Both bounds remain required.

Exchange-wide rows use `ExchangeTrade` and `ExchangeFundingPayment`, subclasses
of the existing records with a required native, exchange-local `market_id`.
The identity can contain colons and is not a fully qualified SDK route.
Market-specific records and streams remain unchanged.

Use native account history endpoints scoped to the selected exchange/account
bucket. Do not implement a generic fallback over currently listed markets.
Unsupported exchange-wide reads raise `NotImplementedError`, even where a
venue supports market-specific reads. Native retention and source coverage
limitations remain visible; no global ordering or unlimited history is promised.
Page requests retain SDK exception translation and retry boundaries. Initial
implementation is limited to Hyperliquid and dYdX; all other venues raise
`NotImplementedError` for exchange-wide reads.

## Alternatives considered

Scanning all current markets cannot recover delisted history and can be costly.
Adding an optional market identity to every market record would weaken the
identity guarantee for exchange-wide results. New method names would duplicate
the existing history operations.

## Consequences

Existing calls remain valid. Consumers opt in with an explicit `None` and receive
market-attributed records. Implementation support is documented per exchange;
fixture tests establish routing, filtering, pagination and parsing behavior, not
live history completeness or release qualification. Venue packages require the
SDK providing these record types when released, following the existing release
policy. No release or live verification is asserted here.

The implementation also corrects existing Hyperliquid and dYdX funding signs to
honor the positive-paid contract. dYdX selected-market history is scoped to its
own exchange subaccount, matching the new exchange-wide reads. These are
observable corrections to existing history results.
