# ADR 0017: Distinguish fill collateral effects from closing PnL

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed (implemented for local review; not released)
2. Date: 2026-09-14

## Context

A futures snapshot represents collateral as equity minus unrealized PnL, paired
with the venue's position entry prices. dYdX weights those prices by cumulative
opening volume, preserving that weight through partial closes. Subsequent opening
fills can therefore redistribute value between collateral and unrealized PnL.
Closing PnL alone does not reconstruct the collateral balance under that convention.

## Decision

1. Preserve independently fetched snapshots and their collateral semantics.
2. Add optional `FutureTrade.collateral_change`: the total fill collateral effect
   in settlement units, excluding fees. It includes `realized_pnl`; consumers must
   not add them together. `None` retains the existing PnL-only effect. Explicit
   zero is meaningful. `balance_change` selects the explicit effect or falls back
   to closing PnL. Missing both remains unknown.
3. Reconstruct dYdX collateral as the native quote-value change plus the change in
   signed position entry value. Reconstruct quantities from signed fills and
   entry prices from cumulative opening volume. A crossing fill starts the new
   lifecycle with its full fill size as opening weight, matching the indexer.
   Snapshots and reported pre-fill context are validation evidence, not balancing
   inputs. Retain deterministic same-time fill ordering.
4. Keep closing PnL separate. Consumers that record closing PnL as a collateral leg
   record the remaining collateral effect separately, rather than labeling all
   collateral redistribution as trading profit. Fees remain separate.

## Alternatives considered

1. Replacing collateral snapshots with native USDC would change the intended
   reporting abstraction and all consumers' valuation assumptions.
2. Relabeling the whole collateral effect as realized PnL loses the distinction
   between closing trades and unrealized-PnL redistribution.
3. Correcting snapshots from replay makes their validation circular.

## Consequences

Consumers must preserve the new field through serialization and reconciliation.
Older consumers that ignore it cannot validate dYdX collateral correctly. A
coordinated SDK, adapter and Portfolio release with dependency floors is required
before publishing; current editable versions are development checkouts, not
released support for this contract. Other venues retain their existing behavior.
Native cash and position checks remain useful independent diagnostics, and a
wallet aggregate match does not establish subaccount allocation completeness.

## References

1. [Collateral model](https://tribulnation.com/blog/margining1.md)
2. [dYdX entry-price aggregation](https://github.com/dydxprotocol/v4-chain/blob/main/indexer/services/ender/src/scripts/helpers/dydx_update_perpetual_position_aggregate_fields.sql)
