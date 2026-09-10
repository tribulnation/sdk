# ADR 0009: Catalogue-owned instrument asset identity

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted
2. Date: 2026-09-10
3. Amends: ADRs 0003, 0006 and 0007; supersedes the remaining base/quote fields from ADR 0001.

## Context

`Rules.base` and `Rules.quote` duplicate Catalogue instrument identity. Hyperliquid
illustrates the ambiguity: spot token indices identify actual tokens, while perp
indices identify contracts, and oracle denominations need not equal collateral.
Forcing those concepts into one venue-wide token namespace is not reliable.

## Decision

1. Remove `Rules.base` and `Rules.quote`, without aliases or inferred replacements.
   Keep trading constraints and `fee_asset`, which identifies an operational fee currency.
2. Consumers obtain base/quote from Catalogue instruments. SDK implementations may
   still read upstream asset metadata internally for account queries and fee logic.
3. Retire the SDK consistency suite's translated-rules check. Do not mark it passed
   or manufacture translations from the instrument being tested. Independent asset
   verification belongs to a later Catalogue check against upstream metadata.
4. Preserve exchange/kind/native-ID checks, exact identity round trips, ticker/stat
   selection semantics and ticker/depth comparisons. Missing markets remain explicit
   deferred coverage. Generic live market tests still validate Rules constraints.
5. Use consistency payload version 2 without asset observations. Reject old report
   schemas and retired checks; fingerprints require fresh qualification runs.

## Consequences

This is a public contract removal. Constructors and direct readers must migrate
with the SDK release; all implementations and examples are updated together.
Two Strats display-only callers can log their known market identifier. No Terminal
collection changes or new quantity-unit abstractions are required.

A passing SDK consistency report no longer asserts independent Catalogue asset
correctness. This limitation is explicit and approved, not a hidden waiver.
Fee currency and quote denomination remain distinct; no global USD/USDC alias is
introduced. Existing dYdX fee currency remains USDC. No release is authorized here.
