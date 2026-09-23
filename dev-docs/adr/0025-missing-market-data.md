# ADR 0025: Missing market data and the MEXC index exclusion

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; implementation and release qualification remain separate.
2. Date: 2026-09-23
3. Amends: ADR 0003 market consistency qualification.

## Context

MEXC advertises KOKUSAISTOCK_USDT but omits its index price from the bulk ticker.
The dedicated public index endpoint also returns success without data. The patched
typed client accepts the native omission. PerpStats.index remains required.

## Decision

Add MissingData as an ApiError subclass for successful venue responses lacking
required market data. It records a native market_id and the SDK field name, without
retaining the response. Existing ApiError handlers continue to catch it. MEXC uses
it for omitted or None index prices; optional mark/funding fields remain None.
No index is fabricated and no market is silently removed from the public SDK API.

Market qualification version 6 recognizes only MEXC perp bulk perp_stats raising
MissingData for KOKUSAISTOCK_USDT, field index. Record excluded/missing_index with
the structured observation. The collector must then successfully request stats for
all remaining discovered markets and record their exact returned IDs. The offline
verifier requires complete, nonempty, unique coverage of those remaining markets.

Other instruments, fields, selected reads, venues, API errors, and unsuccessful or
incomplete follow-up reads fail. Ordinary successful bulk reads retain the normal
policy. This is an explicit unavailable-data exclusion, never a passing bulk read.
Ticker, depth, discovery, selected and empty stats checks remain required unchanged.
A MissingData exception alone is not a general qualification waiver.

## Consequences

Fresh reports are required; old evidence cannot be relabeled. The summary exposes
the exclusion and its public instrument. Other release checks still apply, including
unrelated Bybit and KuCoin schema failures. Publication requires separate approval.
