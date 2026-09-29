"""Product-catalogue reads behind the Advanced Trade spot exchange."""

from typing_extensions import Collection, Literal, Mapping

from tribulnation.sdk.market import Ticker
from tribulnation.sdk.core import ApiError

from typed_coinbase.schemas import PriceBook, Product
from typed_coinbase.app.advanced_trade.http.products.public.list import PublicProduct

from .mixin import ExchangeMixin
from .numbers import parse_optional_decimal

CatalogueProduct = Product | PublicProduct
"""Validated rows from either Advanced Trade catalogue endpoint."""

QUOTE_BATCH_SIZE = 100
"""Bound quote query sizes without making one request per product."""


async def list_products(
  self: ExchangeMixin,
  *,
  product_type: Literal['SPOT'],
) -> list[CatalogueProduct]:
  """Read a complete public catalogue or sweep authenticated pages.

  Args:
    product_type: Which product family to list.
  """
  products = self.app.advanced_trade.http.products
  out: list[CatalogueProduct]
  if self.shared.public:
    response = await self.call_app(
      lambda: products.public.list(product_type=product_type)
    )
    pagination = response.get('pagination')
    # Live small-page sweeps omit products even after removing duplicates.
    # Accept only a complete default response; do not silently return a subset.
    if pagination is None or pagination['has_next'] or pagination.get('next_cursor'):
      raise ApiError('Coinbase public catalogue did not confirm a complete response.')
    out = list(response['products'])
    if response['num_products'] != len(out) or len(
      {p['product_id'] for p in out}
    ) != len(out):
      raise ApiError(
        'Coinbase public catalogue returned inconsistent product identities.'
      )
  else:
    paging = products.list_paged(product_type=product_type)
    out = list(await paging.via(self.call_app))
  return out


def parse_ticker(product: CatalogueProduct, book: PriceBook | None) -> Ticker:
  """Combine catalogue trade statistics with independently observed top of book."""
  bid = (
    max(book['bids'], key=lambda level: level['price'], default=None) if book else None
  )
  ask = (
    min(book['asks'], key=lambda level: level['price'], default=None) if book else None
  )
  return Ticker(
    last=parse_optional_decimal(product['price']),
    bid=bid['price'] if bid else None,
    ask=ask['price'] if ask else None,
    bid_qty=bid['size'] if bid else None,
    ask_qty=ask['size'] if ask else None,
    base_volume_24h=parse_optional_decimal(product['volume_24h']),
  )


def filtered(
  products: list[CatalogueProduct], markets: Collection[str] | None
) -> list[CatalogueProduct]:
  """Keep the requested products, raising when the venue does not list one."""
  if markets is None:
    return products
  wanted = set(markets)
  out = [p for p in products if p['product_id'] in wanted]
  if missing := wanted - {p['product_id'] for p in out}:
    raise ValueError(f'Coinbase markets not found: {", ".join(sorted(missing))}')
  return out


async def tickers(
  self: ExchangeMixin, products: list[CatalogueProduct]
) -> Mapping[str, Ticker]:
  """Read public top-of-book snapshots or authenticated quote batches.

  Omitted books and empty sides remain unknown; failed requests propagate instead
  of silently returning a catalogue-only snapshot. Catalogue and book reads are
  separate observations, not an atomic exchange snapshot.
  """
  books: dict[str, PriceBook] = {}
  ids = [product['product_id'] for product in products]
  if self.shared.public:
    for product_id in ids:
      response = await self.call_app(
        lambda: self.app.advanced_trade.http.products.public.book(product_id, limit=1)
      )
      book = response['pricebook']
      if book['product_id'] != product_id or product_id in books:
        raise ApiError('Coinbase returned an unexpected or duplicate quote product.')
      books[product_id] = book
    return {p['product_id']: parse_ticker(p, books[p['product_id']]) for p in products}
  for offset in range(0, len(ids), QUOTE_BATCH_SIZE):
    batch = ids[offset : offset + QUOTE_BATCH_SIZE]
    quote_response = await self.call_app(
      lambda: self.app.advanced_trade.http.products.best_bid_ask(batch)
    )
    for book in quote_response['pricebooks']:
      product_id = book['product_id']
      if product_id not in batch or product_id in books:
        raise ApiError('Coinbase returned an unexpected or duplicate quote product.')
      books[product_id] = book
  return {
    p['product_id']: parse_ticker(p, books.get(p['product_id'])) for p in products
  }
