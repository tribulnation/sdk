"""Index price and funding state for one INTX perpetual.

Coinbase publishes both through the product catalogue's `future_product_details` blob
rather than through funding endpoints, so there is nothing here to page and nothing
historical to read: see `PerpMarket.funding_rates`/`funding_payments`.
"""

from typing_extensions import Any
from datetime import datetime, timedelta
from decimal import Decimal

from tribulnation.sdk.core import ApiError
from tribulnation.sdk.market import NextFunding

from typed_coinbase.schemas import Product
from typed_coinbase.core import timestamp_iso

from tribulnation.coinbase.core import wrap_exceptions
from .mixin import MarketMixin


def future_details(self: MarketMixin, product: Product, /) -> dict[str, Any]:
  """The product's `future_product_details` blob, or an error naming what is missing."""
  details = product.get('future_product_details')
  if not details:
    raise ApiError(
      f'Coinbase reports no perpetual detail for {self.product_id}; only INTX '
      'perpetuals carry `future_product_details`.'
    )
  return details


def funding_interval(details: dict[str, Any], /) -> timedelta:
  """Parse the catalogue's `funding_interval` (`'3600s'`) into a `timedelta`."""
  return timedelta(seconds=int(str(details['funding_interval']).removesuffix('s')))


def next_funding_time(details: dict[str, Any], /) -> datetime:
  """The upcoming settlement time.

  The catalogue's `funding_time` is the settlement that just *happened*, not the one
  coming: polled across an hour boundary it held 15:00:00Z for the whole of 15:00-16:00
  and flipped to 16:00:00Z six seconds after the hour. So the next payment is one
  interval later.
  """
  last = timestamp_iso.parse(details['perpetual_details']['funding_time'])
  return last + funding_interval(details)


@wrap_exceptions
async def index(self: MarketMixin) -> Decimal:
  """Fetch the perpetual's index price."""
  product = await self.shared.load_product(self.product_id, refetch=True)
  return Decimal(future_details(self, product)['index_price'])


@wrap_exceptions
async def next_funding(self: MarketMixin) -> NextFunding:
  """Fetch the perpetual's upcoming funding rate, time and interval."""
  product = await self.shared.load_product(self.product_id, refetch=True)
  details = future_details(self, product)
  return NextFunding(
    rate=Decimal(details['perpetual_details']['funding_rate']),
    time=next_funding_time(details),
    interval=funding_interval(details),
  )
