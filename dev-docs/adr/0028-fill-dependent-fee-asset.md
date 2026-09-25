# ADR 0028: Fill-dependent fee asset in market rules

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; implementation checks do not establish release qualification.
2. Date: 2026-09-25

## Context

`Rules.fee_asset` names one asset per market. Lighter charges spot fees in the asset
the fill delivers: the base asset on a buy and the quote asset on a sell. Live testnet
fills on both roles and sides matched balance changes exactly under that rule. No
single string describes such a market. Naming the quote asset would misstate every
buy, and naming neither would require inventing a value.

## Decision

Widen `Rules.fee_asset` to `str | None`. A string keeps its meaning: the one asset
trading fees and funding are paid in. `None` means the fee asset depends on the fill;
`Trade.fee.asset` then names it for each fill. `None` is not a placeholder for an
unknown asset: a venue whose fee asset is unknown must not publish rules that claim one.

Lighter spot markets return `None`. Lighter perpetuals return USDC's asset id.
Existing venues keep their current values.

## Alternatives considered

- The quote asset, as a representative value: rejected because it is wrong for
  every buy and silently misleads fee accounting.
- Side-specific fields (`fee_asset_buy`, `fee_asset_sell`): more precise for Lighter,
  but a larger contract for a single venue, and other venues' rules may vary by more
  than side (fee-token discounts). Reconsider if a second venue needs it.

## Consequences

Constructors keep working. Consumers that assumed a string must handle `None`; type
checkers flag those reads. Venue packages returning `None` must require the SDK version
containing this change. The live read suite accepts `None` alongside a non-empty id.
