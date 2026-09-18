# %%
"""Read-only comparison for issue #49; keep production routing unchanged."""

from collections import Counter
from dataclasses import asdict
from importlib.metadata import version
from typing_extensions import Literal

from dotenv import load_dotenv
from typed_coinbase import Coinbase
from typed_coinbase.schemas import Product
from typed_coinbase.app.advanced_trade.http.products.public.list import PublicProduct
from tribulnation.coinbase.market.impl.catalogue import parse_perp_stats, parse_ticker

load_dotenv()
print(
  {
    name: version(name)
    for name in ('typed-coinbase', 'tribulnation-coinbase', 'tribulnation-sdk')
  }
)

STATIC_FIELDS = (
  'product_type',
  'product_venue',
  'base_display_symbol',
  'quote_display_symbol',
  'quote_increment',
  'base_increment',
  'base_min_size',
  'quote_min_size',
  'base_max_size',
  'trading_disabled',
)


async def compare_catalogue(
  product_type: Literal['SPOT', 'FUTURE'],
  *,
  limit: int | None = None,
  sort: Literal['PRODUCTS_SORT_ORDER_LIST_TIME_DESCENDING'] | None = None,
):
  """Compare complete validated catalogues using the implementation's filters."""
  expiry: Literal['PERPETUAL'] | None = (
    'PERPETUAL' if product_type == 'FUTURE' else None
  )
  async with Coinbase.new() as private, Coinbase.new(public=True) as public:
    private_rows = list(
      await private.app.advanced_trade.http.products.list_paged(
        limit=limit,
        products_sort_order=sort,
        product_type=product_type,
        contract_expiry_type=expiry,
      )
    )
    public_rows: list[PublicProduct] = []
    cursor = None
    seen: set[str] = set()
    pages: list[int] = []
    while True:
      page = await public.app.advanced_trade.http.products.public.list(
        limit=limit,
        products_sort_order=sort,
        product_type=product_type,
        contract_expiry_type=expiry,
        cursor=cursor,
      )
      public_rows.extend(page['products'])
      pages.append(len(page['products']))
      pagination = page.get('pagination')
      cursor = pagination.get('next_cursor') if pagination else None
      if not cursor:
        break
      if cursor in seen:
        raise RuntimeError('Public pagination repeated a cursor')
      seen.add(cursor)
    auth = {
      p['product_id']: p
      for p in private_rows
      if product_type == 'SPOT' or p.get('product_venue') == 'INTX'
    }
    anon = {
      p['product_id']: p
      for p in public_rows
      if product_type == 'SPOT' or p.get('product_venue') == 'INTX'
    }
    common = auth.keys() & anon.keys()
    differences = {
      field: [
        pid for pid in sorted(common) if auth[pid].get(field) != anon[pid].get(field)
      ]
      for field in STATIC_FIELDS
    }
    nested_differences = {
      field: [
        pid
        for pid in sorted(common)
        if (auth[pid].get('future_product_details') or {}).get(field)
        != (anon[pid].get('future_product_details') or {}).get(field)
      ]
      for field in (
        'contract_code',
        'contract_size',
        'contract_expiry_type',
        'funding_interval',
        'funding_rate',
        'funding_time',
      )
    }
    print(
      {
        'nested_differences': {k: v for k, v in nested_differences.items() if v},
        'family': product_type,
        'limit': limit,
        'sort': sort,
        'private_duplicates': len(private_rows)
        - len({p['product_id'] for p in private_rows}),
        'public_duplicates': len(public_rows)
        - len({p['product_id'] for p in public_rows}),
        'private_count': len(auth),
        'public_count': len(anon),
        'public_pages': pages,
        'private_only': sorted(auth.keys() - anon.keys()),
        'public_only': sorted(anon.keys() - auth.keys()),
        'static_differences': {k: v for k, v in differences.items() if v},
        'public_missing_fields': {
          field: sum(field not in p for p in anon.values())
          for field in (*STATIC_FIELDS, 'price', 'volume_24h')
        },
        'private_future_detail_fields': dict(
          Counter(
            k for p in auth.values() for k in (p.get('future_product_details') or {})
          )
        ),
        'public_future_detail_fields': dict(
          Counter(
            k for p in anon.values() for k in (p.get('future_product_details') or {})
          )
        ),
      }
    )


# %%
await compare_catalogue('SPOT')

# %%
await compare_catalogue('FUTURE')


# %%
async def compare_product(product_id: str):
  """Compare single-product rules and actual SDK ticker/stats parser outputs."""
  async with Coinbase.new() as private, Coinbase.new(public=True) as public:
    auth: Product = await private.app.advanced_trade.http.products.get(product_id)
    anon: Product = await public.app.advanced_trade.http.products.public.get(product_id)
    quotes = await private.app.advanced_trade.http.products.best_bid_ask([product_id])
    book = await public.app.advanced_trade.http.products.public.book(
      product_id, limit=1
    )
    print(
      {
        'product_id': product_id,
        'static_differences': {
          field: (auth.get(field), anon.get(field))
          for field in STATIC_FIELDS
          if auth.get(field) != anon.get(field)
        },
        'private_ticker': asdict(
          parse_ticker(
            auth,
            next(
              (b for b in quotes['pricebooks'] if b['product_id'] == product_id), None
            ),
          )
        ),
        'public_ticker': asdict(parse_ticker(anon, book['pricebook'])),
        'private_stats': parse_perp_stats(auth),
        'public_stats': parse_perp_stats(anon),
      }
    )


for product_id in (
  'BTC-USD',
  'ETH-USD',
  'SOL-USD',
  'BTC-PERP-INTX',
  'ETH-PERP-INTX',
  'SOL-PERP-INTX',
):
  try:
    await compare_product(product_id)
  except Exception as error:
    print({'product_id': product_id, 'error_type': type(error).__name__})

# %% [markdown]
# Coverage: catalogue, ticker and rules endpoint parity is tested above; this is
# a focused comparison, not an implementation. Other market methods and catalogue
# translation are outside this test (no new SDK IDs are emitted).

# %%
await compare_catalogue('SPOT', limit=100)
await compare_catalogue('FUTURE', limit=100)

# %%
await compare_catalogue(
  'SPOT', limit=100, sort='PRODUCTS_SORT_ORDER_LIST_TIME_DESCENDING'
)
