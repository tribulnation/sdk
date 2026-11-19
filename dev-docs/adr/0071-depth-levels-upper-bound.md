# ADR 0071: Depth `levels` is an upper bound

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; amends [0019](0019-kucoin-public-market.md) and
   [0021](0021-deribit-public-market.md) (their refused depth sizes); implemented, not
   release-verified
2. Date: 2026-11-19

## Context

`Market.depth` and `Market.depth_stream` documented `levels` as a cap on the levels
per side, but venues read it three ways:

1. KuCoin and Deribit raised `ValueError` above their qualified depth (KuCoin 100
   REST and 5 streamed, Deribit 100 REST and 20 streamed), as ADRs 0019 and 0021
   recorded. Aster raised above 20. A caller asking every venue for 50 levels, as the
   strategy engine does since SDK 4.2.0, took those markets down.
2. Binance's partial-depth streams and USD-M REST book, Bybit's, Bit2Me's and MEXC's
   streams and dYdX's REST book and stream delivered more levels than asked (a
   subscribed tier or the whole book), since they ignored `levels` or only used it
   to pick a tier.
3. Kraken spot REST forwarded `levels` as `count`; Kraken answers a count above 500
   with its 100-level default, so asking for 501 served fewer levels than asking for 500.

The remaining venues already served `min(levels, maximum)`.

## Decision

1. `levels` is an upper bound: a venue serves at most `levels` per side, and fewer
   when it publishes fewer. A `levels` above the venue's maximum is served at that
   maximum and never refused. A non-positive `levels` may still raise `ValueError`.
2. Where a venue offers fixed depths (Binance 5/10/20 streamed and 5 to 1000 REST,
   Deribit, KuCoin, Kraken, Bitget futures, GRVT), it requests the smallest
   depth covering `min(levels, maximum)`, or the deepest one, and trims the delivered
   book to `levels`.
3. Venues trim each subscriber's own copy of a shared book (`detached_books(stream,
   levels)`), so one subscriber's `levels` never resizes another's.
4. `None` keeps each venue's documented default.

## Alternatives considered

- Keep refusing sizes above a venue's maximum: it turns a request any venue could
  partly serve into an outage, and callers cannot know each venue's maximum without
  reading its implementation.
- Fail only above an SDK-wide maximum: there is no common maximum, and the caller would
  still need a per-venue table.
- Report the served depth separately: the book's own `len(bids)`/`len(asks)` already
  tells the caller what was served.

## Consequences

- KuCoin and Deribit stop raising for large `levels`; their tests now assert the cap.
- Binance, Bybit, Bit2Me, MEXC and dYdX books are trimmed to `levels`, so callers that
  relied on receiving the whole tier or book for a small `levels` now get `levels`.
  dYdX streams now hand each subscriber a copy, as ADR 0049 requires.
- Kraken spot REST caps `count` at 500.
- The SDK change is documentation only (`Market.depth`/`depth_stream` and
  `TradingMarkets` docstrings); no `tribulnation-sdk` release is needed for it. Each
  adapter change ships in that adapter's next release, with the usual evidence.
- Aster's change is tracked separately.
