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

## Ticker quotes and product identity

`spot` represents Coinbase Advanced Trade spot products. IDs remain native Advanced
Trade product IDs, such as `BTC-USD`. INTX perpetuals are not supported: Coinbase
retires them on the Advanced Trade API on 2026-10-01, moving international
derivatives to a Deribit-powered gateway ([ADR 0031](https://github.com/tribulnation/sdk/blob/main/dev-docs/adr/0031-coinbase-drop-intx.md)).

`Coinbase(public=True)` supports spot market discovery, rules and tickers without
credentials. Public discovery uses the
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
