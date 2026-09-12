# ADR 0014: Preserve Bit2Me native tickers with an explicit quote limitation

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted
2. Date: 2026-09-12
3. Amends: [ADR 0003](0003-local-consistency-release-evidence.md) and
   [ADR 0011](0011-liquidity-independent-consistency.md).

## Context

Local reads found Bit2Me's native Trading Spot ticker ask for 1INCH/EUR at
0.0823 while its live book ask was 0.0790. A1X/USDC returned zero ticker bid/ask
despite a two-sided book. These also occurred on symbol-specific ticker reads;
a recent upstream timestamp did not guarantee usable quotes. The SDK faithfully
mapped these values. No finding here establishes incorrect last prices or volumes.

## Decision

1. Preserve native ticker values. Do not substitute depth-derived prices or add
   book requests to bulk collection. Consumers needing current book quotes should
   explicitly request `depth()`; ticker bid/ask is not a reliable executable spread.
2. Continue all deterministic ticker/depth samples and retain public observations.
   Bit2Me `spot` native quote discrepancies are `limitation/native_ticker_quotes`,
   never passes. This narrowly reviewed upstream limitation does not block release.
3. Require three complete, timely brackets with exact ticker IDs and valid positive,
   non-crossed two-sided books. Ticker sides may be absent, zero or stale nonnegative
   finite prices. All three comparisons must disagree. Negative/malformed prices,
   request errors, slow/incomplete brackets and wrong IDs are not covered.
4. All other consistency and read-suite requirements remain mandatory. Do not widen
   tolerances, choose easier samples, waive another venue or infer new limitations.
   Offline verification independently recomputes eligibility from observations.
5. Record the limitation in developer guidance, generated evidence summaries and
   Bit2Me release notes. Market payload version 4 requires fresh runs, not relabeled
   historical failures. Native zero values are not silently changed to missing values.

## Alternatives considered

1. Derive tickers from depth: rejected to preserve native behavior and request cost.
2. Block release for faithfully reproduced upstream quotes: conflates upstream data
   quality with adapter correctness.
3. Pass or suppress the comparisons: hides unresolved consistency findings.

## Consequences

Release eligibility no longer means every Bit2Me quote matched its book. The failed
comparisons stay inspectable and the exception is bounded by venue, exchange and
observation shape. Existing source fingerprints become stale and qualification
must be rerun. Acceptance is not verification, merge approval or publication approval.
