# Public market endpoint comparison — issue #49

Live read-only checks on 2026-09-18 used existing Coinbase environment credentials
for authenticated calls and a separate `Coinbase.new(public=True)` client for public
calls. Validation remained enabled. No production code was changed.

Environment: typed-coinbase 0.4.0, tribulnation-coinbase 0.2.1,
tribulnation-sdk 2.0.2. Reproduce with:

```sh
.venv/bin/sdk-dev poc run packages/impl/coinbase/poc/public_market.py --cells 1-6
```

## Findings

- Default catalogue reads returned identical sets: 925 spot and 131 INTX perpetuals,
  without duplicates. Repeated default reads matched.
- All products carried the ticker and rule fields checked by the script. Product
  type, venue, base/quote display symbols, increments, quantity/value limits and
  trading-disabled flags matched exactly across common rows.
- All 131 INTX rows carried future product details on both endpoints. Contract code,
  size and expiry type, funding rate, funding time and funding interval matched.
- Public and private single-product reads for BTC, ETH and SOL spot/INTX had identical
  checked rule fields. Both fed the existing SDK ticker and perpetual-stat parsers
  successfully. Public books provided native bid/ask prices and sizes.
- Dynamic fields differed between requests (prices, sizes, index, mark, volume and
  open interest). These non-atomic observations establish field availability and
  parser compatibility, not equal freshness or simultaneous numerical equality.
- Forced 100-row spot pagination was inconsistent on **both** endpoints. In the
  final run, authenticated reads yielded 919 unique products with 13 duplicates;
  public reads yielded 912 unique products with 11 duplicates. Requesting listing-time
  descending order also failed to stabilize coverage: 915/923 unique products with
  8/4 duplicates respectively. Cause is unresolved; changing volume order alone is
  insufficient to explain the result. INTX pagination returned the same 131 IDs
  across two pages without duplicates.

## Implications for a later implementation

Public catalogue and single-product responses support the tested SDK field mappings.
Retain authenticated behavior for credentialed accounts. Public tickers also need a
public quote path: current `best_bid_ask` is signed, while public `book(limit=1)` was
verified for six sample products. That changes request fan-out from batches to one
request per product; whole-catalogue quote throughput was not tested. Rules currently
load products through signed `products.get`, so listing changes alone are insufficient.
Do not claim paginated discovery completeness from these results.

This comparison does not implement routing or prove the existing public MarketSDK
works end to end. No fees, trading, account positions, streams, or unrelated methods
were tested. Catalogue translation is outside scope because no SDK IDs were changed.

## Validation

All six comparison cells executed. The new script passes Ruff and has no diagnostics
in `sdk-dev poc check coinbase`. That command remains failing on four pre-existing
errors in `poc/market.py`: obsolete `maker_fee`/`taker_fee` arguments at lines
119–120 and 410–411. The paired notebook holds local detailed observations and is
ignored by Git.

## Pagination investigation follow-up

`product_pagination.py` isolates direct typed endpoint calls from the generated
pager. Run all seven read-only cells with `sdk-dev poc run ... --cells 1-7`.
All responses retain normal validation; the wire observer logs only public request
URLs and selected response cache headers, never authentication headers.

Repeated experiments compared public/private endpoints, cursor/offset paging,
and default/listing-time sorting, with full snapshots before and after each sweep.
Every bracketing snapshot contained the same 925 distinct spot IDs. Page membership
and ordering nevertheless changed. In the final run:

| Endpoint | Paging | Sort | Unique IDs / 925 |
| --- | --- | --- | --- |
| Public | Cursor | Default | 925 |
| Public | Cursor | Listing time | 920 |
| Public | Offset | Default | 923 |
| Public | Offset | Listing time | 925 |
| Authenticated | Cursor | Default | 923 |
| Authenticated | Cursor | Listing time | 895 |
| Authenticated | Offset | Default | 910 |
| Authenticated | Offset | Listing time | 910 |

Earlier sweeps missed products in all eight combinations. Some later sweeps complete,
so this is intermittent, not a fixed endpoint-specific subset. Exact duplicated IDs,
page numbers, missing IDs, page boundaries and decoded cursors are retained locally
in the notebook. The cursors identify products (`products_cursor:<product_id>`),
not an observable snapshot version. The generated pager forwards the returned cursor;
direct calls reproduce the problem without using that helper.

The outgoing public URL includes `products_sort_order` exactly as requested.
Nevertheless, both explicit sort orders started with BTC-USD/BTC-USDC/ZEC-USD/
ZEC-USDC/ETH-USD. Under listing-time sort, those products have `new_at` in 2023,
while 472 later rows have newer timestamps. The returned order therefore does not
match descending `new_at`. Coinbase's [endpoint documentation](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/public/list-public-products)
exposes both cursor/offset paging and these sort options; `num_products` counts
returned rows, not an independently supplied catalogue total.

Public responses advertised `Cache-Control: public, max-age=14400`; observed probe
responses had `CF-Cache-Status: MISS` and no Age header. Independently cached page
snapshots are a possible contributor, not a proven explanation. Do not infer actual
four-hour staleness from cache policy alone. The exact backend cause remains unknown.

Both default full responses explicitly reported 925 returned rows, 925 unique IDs,
`has_next=False`, and an empty next cursor. Recommendation: preserve default full
catalogue requests for the routing change, check completion metadata, and handle an
unexpected continuation explicitly rather than claim paginated completeness. Do not
use deduplication, offset paging, or the sort flag as a completeness fix. Track the
upstream pagination behavior separately from the public-auth routing defect.

All seven diagnostic cells executed successfully. Ruff passes, and the new diagnostic
has no type/execution errors in the Coinbase PoC check. The same four pre-existing
`market.py` type errors remain. No production code or typed-client code was changed.

## Public routing implementation

After the investigation, production routing was updated for explicitly configured
`Coinbase(public=True)` accounts. Public list reads require a complete default
response, single-product reads use public `get`, and public tickers fetch native
`book(limit=1)` quotes per selected product. Authenticated routes retain their
existing catalogue pager, product lookup, and batched quotes. Coinbase remains
opt-in rather than joining default public accounts; full-catalogue public ticker
fan-out has not been qualified.

Validation of the refactor:

- Coinbase tests plus SDK-dev integration-unit tests: 74 passed.
- Pyright on Coinbase implementation and the new public regression module: clean.
- Ruff on changed Python files: clean; generated documentation check: clean.
- Live public MarketSDK conformance: 16 passed, 4 expected spot/perpetual skips.
- Live authenticated conformance using existing credentials: 16 passed, the same
  4 expected spot/perpetual skips.

The live runs used `integration/market/public.py` with `--sdk-venue coinbase`, once
with an explicit public-only TOML account and once with `sdk.test.toml`. This is
focused market-data verification, not release qualification or a trading test.
