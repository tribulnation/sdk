"""`OrderResponse.filled_qty` from Hyperliquid's per-order statuses."""

from decimal import Decimal
from types import SimpleNamespace
from typing_extensions import Any, cast
from unittest.mock import AsyncMock

import pytest

from tribulnation.hyperliquid.market.impl.mixin import PerpMarketMixin
from tribulnation.hyperliquid.market.impl.orders import place_order
from tribulnation.sdk.market import Order

IOC: Order = {'qty': Decimal('-2'), 'price': Decimal('10'), 'type': 'MARKET'}
GTC: Order = {'qty': Decimal('2'), 'price': Decimal('10'), 'type': 'LIMIT'}


def market(status: dict[str, Any]) -> PerpMarketMixin:
  """A market whose `exchange.order` answers with the single `status`."""
  result: dict[str, Any] = {
    'status': 'ok',
    'response': {'type': 'order', 'data': {'statuses': [status]}},
  }
  order = AsyncMock(return_value=result)
  return cast(
    PerpMarketMixin,
    SimpleNamespace(
      asset_id=3, client=SimpleNamespace(exchange=SimpleNamespace(order=order))
    ),
  )


@pytest.mark.parametrize(
  ('order', 'total'),
  [(IOC, Decimal('1.25')), (IOC, Decimal('2')), (GTC, Decimal('2'))],
)
async def test_filled_reports_total_size(order: Order, total: Decimal):
  """A `filled` status reports its unsigned `totalSz`, partial for an IOC."""
  status: dict[str, Any] = {
    'filled': {'oid': 77, 'avgPx': Decimal('10'), 'totalSz': total}
  }

  response = await place_order(market(status), order)

  assert response.id == '77'
  assert response.filled_qty == total


async def test_filled_accepts_unvalidated_string():
  """With validation off the size arrives as a string and is still parsed."""
  status: dict[str, Any] = {'filled': {'oid': 77, 'avgPx': '10', 'totalSz': '0.5'}}

  response = await place_order(market(status), IOC)

  assert response.filled_qty == Decimal('0.5')


async def test_resting_is_unknown():
  """A `resting` status carries no fill size, even if the order partly crossed."""
  response = await place_order(market({'resting': {'oid': 77}}), GTC)

  assert response.id == '77'
  assert response.filled_qty is None
