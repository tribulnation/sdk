# ADR 0023: Native 24-hour quote volume in tickers

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; implementation checks do not establish release qualification.
2. Date: 2026-09-19

## Context

The SDK exposes only base-denominated ticker volume. dYdX supplies quote turnover,
which cannot populate that field, and other venues already provide both units.
Discarding quote turnover prevents consumers from reading the native traded value.

## Decision

Add `Ticker.quote_volume_24h: Decimal | None = None`, alongside `base_volume_24h`.
It is the venue's native trailing 24-hour turnover in the market's quote currency,
not a conversion to a common USD currency. The venue defines the rolling window;
snapshots across venues need not have identical boundaries. Preserve reported zero;
use `None` for unavailable data. Base and quote availability are independent.

Map native fields for these supported products:

| Venue | Products | Field |
| --- | --- | --- |
| Binance | Spot, USD-M perpetuals | `quoteVolume` |
| Bit2Me | Spot | `quoteVolume` (optional) |
| Bitget | Spot, linear perpetuals | `quoteVolume` |
| Bybit | Spot, linear perpetuals | `turnover24h` |
| Deribit | Spot, linear perpetuals | `volume_notional` (optional) |
| dYdX | Perpetuals | `volume24H` |
| Hyperliquid | Spot, perpetuals | `dayNtlVlm` |
| Kraken | Linear perpetuals | `volumeQuote` |
| KuCoin | Spot / linear perpetuals | `volValue` / `turnoverOf24h` |
| MEXC | Spot / linear perpetuals | `quoteVolume` / `amount24` |

MEXC spot switches from the book ticker to the full 24h ticker endpoint, preserving
one bulk request while adding last price and both volumes. Other mappings reuse
existing responses. Deribit uses quote notional, never its USD-normalized field.
Coinbase and Kraken spot leave quote volume unavailable. dYdX base volume remains
unavailable. Asset identity continues to belong to the Catalogue (ADR 0009).

## Alternatives considered

- Multiply base volume by the latest price: rejected because it does not recover
  traded value at the historical execution prices.
- Derive turnover from rounded VWAP or candles: excluded from this native field.
- Normalize all turnover to USD: a separate conversion concern, especially for
  non-USD quote assets. No stablecoin/fiat conversion is implied.

## Consequences

Existing `Ticker` constructors remain valid through the optional default. Consumers
serializing all dataclass fields receive an additional optional field. Venue packages
must require the SDK version containing this field when released; release version
bumps and live qualification remain separate. Regression coverage preserves Decimal
precision, independent units, optional absence and real zeros.
