# ADR 0004: Empty books and non-vacuous quote coverage

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; liquidity requirement superseded by [ADR 0011](0011-liquidity-independent-consistency.md)
2. Date: 2026-09-10
3. Amends: [ADR 0003](0003-local-consistency-release-evidence.md), quote availability policy only.

## Context

An SDK market can legitimately have an empty order book. Three Binance sample
brackets returned neither book sides nor ticker quotes for two markets. This
does not establish a price mismatch, but also cannot establish price consistency.
Blocking the whole venue on these observations confuses liquidity with correctness.

## Decision

1. Preserve a fully empty sampled market as `unavailable` with code `empty_book`,
   never as a passing price comparison. All three attempts must return the exact
   ticker ID, complete within 15 seconds, and contain no bid or ask in either book
   snapshot or the ticker. The offline verifier recomputes these requirements.
2. Require at least one successful two-sided quote comparison on every discovered
   exchange supporting depth and tickers. An exchange with only empty samples
   still blocks release. Samples are not removed or replaced to conceal failures.
3. Missing rows, request failures, inconsistent or partially missing quotes, stale
   brackets, and persistent mismatches remain blocking. Other checks and their
   capability exclusions are unchanged.
4. CLI success describes satisfaction of the coverage policy, not a claim that
   every recorded observation passed. Empty observations remain in saved reports.

## Alternatives considered

1. Mark empty snapshots as matching prices: would invent price evidence.
2. Accept any unavailable quote: could hide adapter failures or a fully untested exchange.
3. Require every sampled market to have liquidity: would make market activity an
   undocumented implementation guarantee.

## Consequences

Legitimately empty samples need not block an otherwise verified exchange. This
narrow exception does not waive real quote coverage or certify unsampled markets.
One-sided books remain unavailable and blocking under this initial policy.
