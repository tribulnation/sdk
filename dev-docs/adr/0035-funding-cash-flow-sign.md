# ADR 0035: Funding payments use received-positive cash flows

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; supersedes the funding sign decision in [ADR 0024](0024-exchange-account-history.md).
2. Date: 2026-10-05

## Context

The SDK documented funding payments as positive when paid. ADR 0024 changed
Hyperliquid and dYdX to match that wording, reversing their existing cash-flow
signs. Account histories and Report funding observations are easier to reconcile
when a positive amount consistently increases the account balance.

## Decision

`FundingPayment.amount` and `ExchangeFundingPayment.amount` are quote-denominated
account cash flows: positive means received, negative means paid, and zero stays
zero. Apply this to market-specific and exchange-wide history uniformly.
Hyperliquid, dYdX, Bybit, Aster and Lighter preserve the received-positive native
fields they already read. Unsupported adapters remain unsupported.

Funding rates keep their existing convention: positive means longs pay shorts.
Trading fees also retain their expense-positive convention. Report observations
already use credited-positive amounts and do not change.

Release this breaking contract as SDK 3.0.0 and new minor versions of the five
pre-1.0 adapters, each requiring SDK >=3.0.0. Consumers must upgrade those adapters
together with the SDK; older published adapters have unbounded SDK requirements
and cannot be made compatible retroactively. Negate stored amounts from the
previous paid-positive versions exactly once, or refetch history. Do not negate
older Hyperliquid/dYdX records already stored with received-positive signs.

## Alternatives considered

Keep paid-positive amounts: preserves the written contract but makes funding
income the opposite sign of cash-flow reporting. Change only Hyperliquid and
dYdX: restores earlier behavior but makes the same SDK field venue-dependent.

## Consequences

Summing payment amounts gives net funding income. This is an intentional breaking
migration, not a claim that the old adapters violated their documented contract.
Fixtures cover positive, negative and zero amounts and both history scopes where
supported. Read-only release suites qualify the candidate surfaces; they do not
prove personal history completeness or replace sign regression fixtures.
