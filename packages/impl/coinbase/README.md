# Coinbase SDK

> Tribulnation SDK implementation for Coinbase.

## Installation

```bash
pip install tribulnation-coinbase
```

## Public perpetual funding history

INTX markets expose `funding_rates(start=None, end=None)` through Coinbase's
credential-free International Exchange API. SDK IDs remain Advanced Trade IDs,
such as `BTC-PERP-INTX`; the adapter resolves the corresponding native instrument
before reading history. Bounds are inclusive; omitted start walks the earliest
available history. Offset pages are not atomic, and repeated events are
deduplicated. Private funding payments and INTX portfolio access are separate.

## Ticker quotes and product identity

`spot` represents Coinbase Advanced Trade spot products; `intx` represents
International Exchange perpetuals accessed through Advanced Trade. IDs remain
native Advanced Trade product IDs, such as `BTC-USD` and `BTC-PERP-INTX`.

Bulk tickers combine catalogue last-trade prices and base volumes with the
[best-bid/ask endpoint](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/products/get-best-bid-ask),
including quoted sizes. Quotes are fetched in bounded batches for the selected
products, under the caller's retry context. A missing book or empty side remains
`None`; request failures propagate. The two sources are separate observations,
not an atomic snapshot. These reads retain the existing Advanced Trade credential
requirement and do not fetch the app's simple-buy quotes.
