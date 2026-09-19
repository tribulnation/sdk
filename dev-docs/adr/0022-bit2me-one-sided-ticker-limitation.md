# ADR 0022: Bit2Me native ticker limitation with stable one-sided books

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; implementation and release qualification remain separate.
2. Date: 2026-09-19
3. Amends: [ADR 0014](0014-bit2me-native-ticker-limitation.md).

## Context

Repeated validated public reads of Bit2Me `spot:A1X/USDC` returned ticker bid/ask
`0.0`, no book bids, and a book ask of `0.0005999`. The adapter preserved these
native values. Three timely brackets in each of two full consistency runs showed
the same discrepancy; a subsequent native-versus-SDK probe confirmed the mapping.
ADR 0014 recognizes this upstream ticker limitation only with two-sided books.
The absence of liquidity on one side does not establish a different adapter defect.

## Decision

Extend only Bit2Me spot's existing `limitation/native_ticker_quotes` eligibility
to stable one-sided books. Require all of the following:

1. Three timely, exact-ID brackets whose ticker/book comparisons all disagree.
2. The same nonempty book-side inventory in all six depth snapshots: bid only,
   ask only, or both. A side appearing or disappearing fails this exception.
3. Every present book price is finite and positive; two-sided books are not crossed.
4. Native ticker sides may be missing, zero or stale nonnegative finite prices.
   Preserve the original values and public observations; the discrepancy is a
   visible limitation, never a passing quote comparison.

Completely empty books, malformed/negative prices, request errors, slow brackets,
wrong IDs, incomplete attempts and other venues' mismatches remain outside this
exception. Keep the existing tolerances, deterministic samples and all other gates.
The offline verifier recomputes eligibility from the saved observations.

Market payload version 5 requires fresh recorded runs. Historical failures are
not relabeled. Publication remains subject to all release checks and maintainer
authorization.

## Consequences

A stable one-sided Bit2Me book can qualify the known native ticker limitation
without guaranteeing liquidity or inventing quotes. Consumers still request depth
for current book quotes. All read suites and Market consistency must be refreshed
against the final candidate and Catalogue; passing policy alone is insufficient.
