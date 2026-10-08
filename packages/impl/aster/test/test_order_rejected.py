"""`place_order` raises `OrderRejected` only for Aster's definitive refusals."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from typed_aster import (
  ApiError as ClientApiError,
  BadRequest as ClientBadRequest,
  RateLimited as ClientRateLimited,
)
from typed_aster.futures.trade.place_order import PlaceOrder as PerpOrders
from typed_aster.spot.trade.place_order import PlaceOrder as SpotOrders
from tribulnation.aster import AsterMarket
from tribulnation.aster.market.markets import PerpMarket, SpotMarket
from tribulnation.sdk.core import ApiError, BadRequest, OrderRejected, RateLimited
from tribulnation.sdk.market import Order

ORDER: Order = {'type': 'POST_ONLY', 'qty': Decimal('1'), 'price': Decimal('0.75')}


def market(scope: str) -> SpotMarket | PerpMarket:
  """A testnet market over a public client, without catalogue requests."""
  shared = AsterMarket.new(public=True, mainnet=False).shared
  cls = PerpMarket if scope == 'perp' else SpotMarket
  return cls(shared=shared, symbol='ASTERUSDT')


def patch(scope: str, monkeypatch: pytest.MonkeyPatch, endpoint: AsyncMock):
  """Route the scope's order placement to `endpoint`."""
  monkeypatch.setattr(
    PerpOrders if scope == 'perp' else SpotOrders, 'place_order', endpoint
  )


@pytest.mark.parametrize('scope', ['spot', 'perp'])
@pytest.mark.parametrize(
  'body',
  [
    {'code': -2019, 'msg': 'Margin is insufficient.'},
    {'code': -1111, 'msg': 'Precision is over the maximum defined for this asset.'},
    {'code': -5022, 'msg': 'Post Only order will be rejected.'},
  ],
)
async def test_coded_4xx_is_rejected(
  scope: str, body: dict[str, object], monkeypatch: pytest.MonkeyPatch
):
  """A `4XX` with a business code never reached the matching engine."""
  patch(scope, monkeypatch, AsyncMock(side_effect=ClientBadRequest(400, body)))

  with pytest.raises(OrderRejected) as raised:
    await market(scope).place_order(ORDER)

  assert raised.value.args == (400, body)


@pytest.mark.parametrize('scope', ['spot', 'perp'])
@pytest.mark.parametrize(
  ('status', 'body'),
  [
    (400, {'code': -1007, 'msg': 'Timeout waiting for response from backend server.'}),
    (400, {'code': -1006, 'msg': 'An unexpected response was received.'}),
    (400, {'code': -1000, 'msg': 'An unknown error occurred.'}),
    (408, {'code': -1100, 'msg': 'Request timeout.'}),
    (400, 'not json'),
  ],
)
async def test_unknown_outcome_4xx_stays_bad_request(
  scope: str, status: int, body: object, monkeypatch: pytest.MonkeyPatch
):
  """Timeouts, unknown codes and code-less bodies leave the order's fate open."""
  patch(scope, monkeypatch, AsyncMock(side_effect=ClientBadRequest(status, body)))

  with pytest.raises(BadRequest):
    await market(scope).place_order(ORDER)


@pytest.mark.parametrize('scope', ['spot', 'perp'])
async def test_server_error_is_not_rejected(
  scope: str, monkeypatch: pytest.MonkeyPatch
):
  """A `5XX` means the execution status is unknown."""
  patch(scope, monkeypatch, AsyncMock(side_effect=ClientApiError(503, 'Unknown error')))

  with pytest.raises(ApiError) as raised:
    await market(scope).place_order(ORDER)

  assert not isinstance(raised.value, OrderRejected)


async def test_rate_limit_keeps_its_class(monkeypatch: pytest.MonkeyPatch):
  """Throttling stays `RateLimited`, the class callers retry on."""
  error = ClientRateLimited(429, {'code': -1015, 'msg': 'Too many new orders.'})
  patch('perp', monkeypatch, AsyncMock(side_effect=error))

  with pytest.raises(RateLimited):
    await market('perp').place_order(ORDER)


@pytest.mark.parametrize('status', ['EXPIRED', 'REJECTED'])
async def test_dead_unfilled_result_is_rejected(
  status: str, monkeypatch: pytest.MonkeyPatch
):
  """A final result with nothing filled, e.g. a GTX that would have crossed."""
  row: dict[str, object] = {'orderId': 9, 'status': status, 'executedQty': Decimal('0')}
  patch('perp', monkeypatch, AsyncMock(return_value=row))

  with pytest.raises(OrderRejected):
    await market('perp').place_order(ORDER)


@pytest.mark.parametrize(
  'row',
  [
    {'orderId': 9, 'status': 'EXPIRED', 'executedQty': Decimal('0.5')},
    {'orderId': 9, 'status': 'NEW', 'executedQty': Decimal('0')},
    {'orderId': 9},
  ],
)
async def test_live_or_filled_result_is_returned(
  row: dict[str, object], monkeypatch: pytest.MonkeyPatch
):
  """A partial fill, a resting order and an `ACK` without status are responses."""
  patch('perp', monkeypatch, AsyncMock(return_value=row))

  response = await market('perp').place_order(ORDER)

  assert response.id == '9'
