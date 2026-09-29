# ADR 0030: MEXC bulk stats omit markets without an index

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; unit fixtures verify it, and MEXC Market consistency evidence
   records it.
2. Date: 2026-09-29
3. Amends: [ADR 0025](0025-missing-market-data.md), for MEXC `perp_stats`.

## Context

Under ADR 0025, MEXC's `perp_stats` raised `MissingData` when any ticker row lacked
its index price, so one contract failed a read of the whole universe. MEXC keeps
listing stock perpetuals without an index: `KOKUSAISTOCK_USDT` first, and on
2026-09-29 five at once (`KINSUSSTOCK_USDT`, `NANYAPCBSTOCK_USDT`,
`NANYAPLSTSTOCK_USDT`, `YAGEOSTOCK_USDT`, `ZHENDINGSTOCK_USDT`;
[#116](https://github.com/tribulnation/sdk/issues/116)). Each new symbol broke every
bulk read and blocked release qualification, since the consistency exclusion names
one symbol and retries once.

The `perp_stats` contract returns a mapping of market ID to `PerpStats`. It does not
promise that every discovered market appears in it.

## Decision

1. Reading every market (`markets=None`) leaves out contracts whose ticker omits the
   index price, and returns the rest.
2. Naming markets explicitly still raises `MissingData` (`field='index'`) for a named
   market without its index. The caller asked for that market, so dropping it would
   hide the gap.
3. No index is fabricated. Rows the venue does not return at all still fail the
   snapshot, as before.

This replaces ADR 0025's "no market is silently removed" for MEXC bulk `perp_stats`
only. `MissingData` itself and its other uses are unchanged.

## Alternatives considered

- Extend the consistency exclusion to a list of symbols: each new listing would still
  break every bulk read for callers, and need an `sdk-dev` change, which invalidates
  every venue's evidence.
- Omit from explicit selections too: a named market would vanish without an error.

## Consequences

Callers of the bulk read see fewer markets than `markets()` lists while MEXC omits
indices, and must not assume the two sets match. Market consistency passes the bulk
check through its normal subset rule, so qualification no longer depends on which
symbols lack an index. The `KOKUSAISTOCK_USDT` exclusion in `sdk-dev` no longer
triggers; removing it touches `sdk-dev`, so it is left for a release that re-records
every venue anyway.
