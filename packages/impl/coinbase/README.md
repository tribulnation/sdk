# Coinbase SDK

> Tribulnation SDK implementation for Coinbase.

## Installation

```bash
pip install tribulnation-coinbase
```

## Recommended account configuration

Coinbase is not a default `MarketSDK` account. Configure it explicitly and prefer
an authenticated `accounts.Coinbase()` account, especially for `tickers()`:
authenticated quotes are batched in groups of up to 100 products.

Use `accounts.Coinbase(public=True)` to allow a credential-free fallback. The router
still prefers resolved credentials when available. Without credentials, `tickers()`
makes one public book request per selected product, so pass market IDs
to limit request volume. Authentication failures never trigger an automatic switch
to public endpoints.

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

`Coinbase(public=True)` supports spot and INTX market discovery, rules, tickers,
index prices and funding state without credentials. Public discovery uses the
complete default product response. A response indicating more pages, missing
completion metadata or duplicate IDs raises an error: live small-page sweeps can
omit products, so deduplication cannot guarantee completeness.

Authenticated bulk tickers combine catalogue last-trade prices and base volumes with the
[best-bid/ask endpoint](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/products/get-best-bid-ask),
including quoted sizes. Quotes are fetched in bounded batches for the selected
products, under the caller's retry context. A missing book or empty side remains
`None`; request failures propagate. The two sources are separate observations,
not an atomic snapshot.

Public tickers use one `public.book(limit=1)` request per selected product to obtain
native bid/ask prices and sizes. Pass selected market IDs to limit request volume;
a full exchange sweep needs a book request for every product. Each request uses the
caller's retry context. Account fees, balances and trading still require credentials.
