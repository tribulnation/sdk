"""Index price and funding state for one INTX perpetual.

Coinbase publishes both through the product catalogue's `future_product_details` rather
than through funding endpoints, so there is nothing here to page and nothing
historical to read: see `PerpMarket.funding_rates`/`funding_payments`.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from tribulnation.sdk.core import ApiError
from tribulnation.sdk.market import NextFunding

from typed_coinbase.schemas import FutureProductDetails, Product

from tribulnation.coinbase.core import wrap_exceptions
from .mixin import MarketMixin
from .numbers import parse_optional_decimal


def future_details(self: MarketMixin, product: Product, /) -> FutureProductDetails:
  """The product's `future_product_details`, or an error naming what is missing."""
  details = product.get('future_product_details')
  if not details:
    raise ApiError(
      f'Coinbase reports no perpetual detail for {self.product_id}; only INTX '
      'perpetuals carry `future_product_details`.'
    )
  return details


def funding_interval(details: FutureProductDetails, /) -> timedelta | None:
  """Parse the catalogue's `funding_interval` (`'3600s'`) into a `timedelta`."""
  interval = details.get('funding_interval')
  if not interval:
    return None
  return timedelta(seconds=int(interval.removesuffix('s')))


def funding_rate(details: FutureProductDetails, /) -> Decimal | None:
  """The catalogue's current funding rate.

  Read off the parent rather than the nested `perpetual_details`: INTX perpetuals
  populate both with the same value (verified live across all 131 of them), while
  FCM-managed contracts send no `perpetual_details` at all and publish funding only
  here.
  """
  return parse_optional_decimal(details.get('funding_rate'))


def next_funding_time(details: FutureProductDetails, /) -> datetime | None:
  """The upcoming settlement time.

  The catalogue's `funding_time` is the settlement that just *happened*, not the one
  coming: polled across an hour boundary it held 15:00:00Z for the whole of 15:00-16:00
  and flipped to 16:00:00Z six seconds after the hour. So the next payment is one
  interval later. Read off the parent, for the reason `funding_rate` gives.
  """
  last = details.get('funding_time')
  interval = funding_interval(details)
  if last is None or interval is None:
    return None
  return last + interval


@wrap_exceptions
async def index(self: MarketMixin) -> Decimal:
  """Fetch the perpetual's index price."""
  product = await self.shared.load_product(self.product_id, refetch=True)
  price = parse_optional_decimal(future_details(self, product).get('index_price'))
  if price is None:
    raise ApiError(f'Coinbase publishes no index price for {self.product_id}.')
  return price


@wrap_exceptions
async def next_funding(self: MarketMixin) -> NextFunding:
  """Fetch the perpetual's upcoming funding rate, time and interval."""
  product = await self.shared.load_product(self.product_id, refetch=True)
  details = future_details(self, product)
  rate = funding_rate(details)
  time = next_funding_time(details)
  interval = funding_interval(details)
  if rate is None or time is None or interval is None:
    raise ApiError(
      f'Coinbase publishes no funding state for {self.product_id}; only contracts '
      'with a funding mechanism carry a rate, a settlement time and an interval.'
    )
  return NextFunding(rate=rate, time=time, interval=interval)
