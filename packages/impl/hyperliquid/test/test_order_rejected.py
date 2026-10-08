"""`place_order` raises `OrderRejected` only for Hyperliquid's definitive refusals."""

from decimal import Decimal
from types import SimpleNamespace
from typing_extensions import Any, cast
from unittest.mock import AsyncMock

import pytest
from typed_hyperliquid import core

from tribulnation.hyperliquid.market.impl.mixin import PerpMarketMixin
from tribulnation.hyperliquid.market.impl.orders import place_order
from tribulnation.sdk.core import ApiError, OrderRejected
from tribulnation.sdk.market import Order

ORDER: Order = {'qty': Decimal('1'), 'price': Decimal('10'), 'type': 'MARKET'}
IOC_NO_MATCH = 'Order could not immediately match against any resting orders. asset=3'


def market(endpoint: AsyncMock) -> PerpMarketMixin:
  """A market whose client's `exchange.order` is `endpoint`."""
  return cast(
    PerpMarketMixin,
    SimpleNamespace(
      asset_id=3, client=SimpleNamespace(exchange=SimpleNamespace(order=endpoint))
    ),
  )


def ok(*statuses: Any) -> dict[str, Any]:
  """An accepted action carrying the given per-order statuses."""
  return {
    'status': 'ok',
    'response': {'type': 'order', 'data': {'statuses': list(statuses)}},
  }


async def test_per_order_error_is_rejected():
  """A processed order whose status is an error never rested nor filled."""
  endpoint = AsyncMock(return_value=ok({'error': IOC_NO_MATCH}))

  with pytest.raises(OrderRejected) as raised:
    await place_order(market(endpoint), ORDER)

  assert raised.value.args == (IOC_NO_MATCH,)


async def test_action_error_is_rejected():
  """A top-level `err` refuses the whole action before any order is processed."""
  endpoint = AsyncMock(
    return_value={'status': 'err', 'response': 'User or API Wallet does not exist.'}
  )

  with pytest.raises(OrderRejected):
    await place_order(market(endpoint), ORDER)


@pytest.mark.parametrize(
  'status',
  [
    {'filled': {'oid': 77, 'avgPx': Decimal('10'), 'totalSz': Decimal('1')}},
    {'resting': {'oid': 77}},
  ],
)
async def test_accepted_order_returns_response(status: dict[str, Any]):
  """Filled and resting orders both answer with the venue's order ID."""
  response = await place_order(market(AsyncMock(return_value=ok(status))), ORDER)

  assert response.id == '77'
  assert response.details == status


async def test_empty_statuses_are_not_definitive():
  """A response without the order's status leaves its outcome unknown."""
  endpoint = AsyncMock(return_value=ok())

  with pytest.raises(ApiError) as raised:
    await place_order(market(endpoint), ORDER)

  assert not isinstance(raised.value, OrderRejected)


async def test_http_error_is_not_definitive():
  """A non-200 response (e.g. a 5xx) may hide an accepted order."""
  endpoint = AsyncMock(side_effect=core.ApiError(502, 'Bad Gateway'))

  with pytest.raises(ApiError) as raised:
    await place_order(market(endpoint), ORDER)

  assert not isinstance(raised.value, OrderRejected)
  assert raised.value.args == (502, 'Bad Gateway')
