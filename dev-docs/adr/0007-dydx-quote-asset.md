# ADR 0007: dYdX quote and fee assets are USDC

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; quote field removed by [ADR 0009](0009-catalogue-owned-asset-identity.md), fee currency unchanged
2. Date: 2026-09-10

## Context

Native dYdX instrument names end in `-USD`, but the technical margin documentation
identifies USDC as the quote asset and describes `quoteBalance` as USDC. Deriving
the financial asset from the instrument-name suffix made SDK rules disagree with
the Catalogue and reported the fee asset as fiat USD.

## Decision

Return `USDC` for both `rules().quote` and `rules().fee_asset`. Preserve native
market IDs such as `BTC-USD`, and keep Catalogue quote/settlement as `usd-coin`.
Do not rename native instruments or globally translate the USD symbol to USDC.

## Alternatives considered

Keep suffix-derived USD and change the Catalogue: rejected after checking the
[technical margin documentation](https://docs.dydx.xyz/concepts/trading/margin).
The attempted local Catalogue quote change was undone without publication.

## Consequences

Consumers see corrected asset semantics without a market-ID migration. Regression
tests cover quote and fee asset separately from the unchanged native market name.
