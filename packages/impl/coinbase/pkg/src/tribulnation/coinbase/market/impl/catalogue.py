"""Product-catalogue reads shared by both Advanced Trade exchanges."""

from typing_extensions import Collection, Literal, Mapping

from tribulnation.sdk.market import PerpStats, Ticker
from tribulnation.sdk.core import ApiError

from typed_coinbase.schemas import PriceBook, Product

from .funding import funding_interval, funding_rate, next_funding_time
from .mixin import ExchangeMixin
from .numbers import parse_optional_decimal

INTX = 'INTX'
QUOTE_BATCH_SIZE = 100
"""Bound quote query sizes without making one request per product."""


async def list_products(
  self: ExchangeMixin,
  *,
  product_type: Literal['SPOT', 'FUTURE'],
  perpetual: bool = False,
) -> list[Product]:
  """Sweep the product catalogue, one `@SDK.method` call per page.

  Args:
    product_type: Which product family to list.
    perpetual: Restrict futures to perpetual contracts on INTX.
  """
  paging = self.app.advanced_trade.http.products.list_paged(
    product_type=product_type,
    contract_expiry_type='PERPETUAL' if perpetual else None,
  )
  out = list(await paging.via(self.call_app))
  if perpetual:
    return [p for p in out if p.get('product_venue') == INTX]
  return out


def parse_ticker(product: Product, book: PriceBook | None) -> Ticker:
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


def parse_perp_stats(product: Product) -> PerpStats | None:
  """Map one INTX perpetual's catalogue entry onto a `PerpStats`.

  Returns `None` for a product carrying no `future_product_details`, or none whose
  details name an index price: everything a `PerpStats` needs lives in that object,
  and `index` is the one field it has no optional form for.
  """
  details = product.get('future_product_details')
  if not details:
    return None
  index = parse_optional_decimal(details.get('index_price'))
  if index is None:
    return None
  return PerpStats(
    index=index,
    mark=parse_optional_decimal(product.get('mid_market_price')),
    funding=funding_rate(details),
    next_funding_time=next_funding_time(details),
    funding_interval=funding_interval(details),
    open_interest=details.get('open_interest'),
  )


def filtered(products: list[Product], markets: Collection[str] | None) -> list[Product]:
  """Keep the requested products, raising when the venue does not list one."""
  if markets is None:
    return products
  wanted = set(markets)
  out = [p for p in products if p['product_id'] in wanted]
  if missing := wanted - {p['product_id'] for p in out}:
    raise ValueError(f'Coinbase markets not found: {", ".join(sorted(missing))}')
  return out


async def tickers(self: ExchangeMixin, products: list[Product]) -> Mapping[str, Ticker]:
  """Enrich selected products with retriable batches of native bid/ask quotes.

  Omitted books and empty sides remain unknown; failed requests propagate instead
  of silently returning a catalogue-only snapshot. Catalogue and book reads are
  separate observations, not an atomic exchange snapshot.
  """
  books: dict[str, PriceBook] = {}
  ids = [product['product_id'] for product in products]
  for offset in range(0, len(ids), QUOTE_BATCH_SIZE):
    batch = ids[offset : offset + QUOTE_BATCH_SIZE]
    response = await self.call_app(
      lambda: self.app.advanced_trade.http.products.best_bid_ask(batch)
    )
    for book in response['pricebooks']:
      product_id = book['product_id']
      if product_id not in batch or product_id in books:
        raise ApiError('Coinbase returned an unexpected or duplicate quote product.')
      books[product_id] = book
  return {
    p['product_id']: parse_ticker(p, books.get(p['product_id'])) for p in products
  }
