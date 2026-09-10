# ADR 0011: Consistency does not guarantee market liquidity

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted
2. Date: 2026-09-10
3. Amends: ADRs 0003 and 0004; supersedes the two-sided coverage requirement.

## Context

The SDK permits empty and one-sided books. Requiring a successful two-sided
comparison on every exchange accidentally made liquidity a release guarantee.
Live Hyperliquid reads found one-sided spot books and builder exchanges whose
entire upstream universe was explicitly delisted. Neither is an adapter failure.

## Decision

1. Compare each existing ticker side to the same side in the immediately preceding
   and following depth snapshots. All three snapshots must agree on side absence.
   Keep the 15-second bracket, 0.5% tolerance and three-attempt retry policy.
2. A matching one-sided bracket passes for the observed side only. There is no
   requirement for another market or exchange to have a two-sided book.
3. Three timely, consistently empty brackets remain `unavailable/empty_book`, not
   price evidence, but do not block release even if an entire exchange is empty.
   Wrong IDs, persistent missing-side disagreement, invalid prices, request failures
   and stale brackets remain blockers. No missing-side price is synthesized.
4. A sampled instrument explicitly marked delisted in the reviewed Catalogue is
   `excluded/delisted` for quote comparison. Match venue, kind, exchange and native ID
   exactly. The offline verifier checks the flag in the fingerprinted Catalogue;
   discovery, identity round trips and ticker/stat selection checks remain required.
   Populate lifecycle flags only from explicit upstream information, never liquidity.
5. Bump market evidence payloads to version 3. Fresh qualification is required;
   this policy is not permission to relabel existing failed reports.

## Alternatives and consequences

1. Requiring liquidity would block correct implementations for external market state.
2. Treating empty books as price matches would invent verification; preserve absence.
3. Dropping failed or empty samples would conceal findings; keep deterministic samples.

This is a test-policy change, not a public SDK contract change. Catalogue delistings
remain separately reviewed PRs. Testnet-only private account evidence remains outside
the mainnet release policy; this ADR does not waive that requirement or authorize release.
