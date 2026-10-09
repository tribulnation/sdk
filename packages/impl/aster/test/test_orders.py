"""Order semantics and error translation through real SDK market adapters."""

from decimal import Decimal
from unittest.mock import AsyncMock
from urllib.parse import parse_qsl
import pytest
from typed_aster import AuthError as ClientAuthError, BadRequest as ClientBadRequest
from typed_aster.core.endpoint.wire import dump_request
from typed_aster.core.transport.http import encode
from typed_aster.futures.trade.place_order import (
  PlaceOrder as PerpOrders,
  Request as PerpOrderRequest,
)
from typed_aster.spot.trade.place_order import (
  PlaceOrder as SpotOrders,
  Request as SpotOrderRequest,
)
from typed_aster.futures.trade.order import Order as PerpQuery
from typed_aster.spot.trade.order import Order as SpotQuery
from typed_aster.futures.trade.cancel_batch_orders import CancelBatchOrders
from tribulnation.aster import AsterMarket
from tribulnation.aster.market.markets import PerpMarket, SpotMarket
from tribulnation.sdk import AuthError, BadRequest
from tribulnation.sdk.market import Order
from typing_extensions import Literal


def market(scope: str) -> SpotMarket | PerpMarket:
  """A testnet market over a public client, without catalogue requests."""
  shared = AsterMarket.new(public=True, mainnet=False).shared
  cls = PerpMarket if scope == 'perp' else SpotMarket
  return cls(shared=shared, symbol='ASTERUSDT')


@pytest.mark.parametrize('scope', ['spot', 'perp'])
@pytest.mark.parametrize('kind', ['MARKET', 'LIMIT', 'POST_ONLY'])
@pytest.mark.parametrize('qty', [Decimal('12.34'), Decimal('-12.34')])
async def test_signed_order_types(
  scope: str,
  kind: Literal['MARKET', 'LIMIT', 'POST_ONLY'],
  qty: Decimal,
  monkeypatch: pytest.MonkeyPatch,
):
  """MARKET omits price/TIF; GTC and GTX preserve price, sign and native order ID."""
  endpoint = AsyncMock(return_value={'orderId': 123})
  monkeypatch.setattr(
    PerpOrders if scope == 'perp' else SpotOrders, 'place_order', endpoint
  )
  order: Order = {'type': kind, 'qty': qty, 'price': '0.75'}
  placed = await market(scope).place_order(order)
  assert endpoint.await_args is not None
  request = endpoint.await_args.args[0]
  assert placed.id == '123'
  assert request['quantity'] == abs(qty)
  assert request['side'] == ('BUY' if qty > 0 else 'SELL')
  if kind == 'MARKET':
    assert 'price' not in request and 'timeInForce' not in request
  else:
    assert request['price'] == Decimal('0.75')
    assert request['timeInForce'] == ('GTX' if kind == 'POST_ONLY' else 'GTC')


def sent_params(
  scope: str, request: PerpOrderRequest | SpotOrderRequest
) -> dict[str, str]:
  """The query parameters typed-aster signs and sends for a captured order request."""
  params = dump_request(
    request, PerpOrderRequest if scope == 'perp' else SpotOrderRequest
  )
  assert params is not None
  return dict(parse_qsl(encode(list(params.items()))))


@pytest.mark.parametrize('scope', ['spot', 'perp'])
@pytest.mark.parametrize('kind', ['MARKET', 'LIMIT', 'POST_ONLY'])
@pytest.mark.parametrize(
  ('qty', 'expected'),
  [
    ('1.9E+2', '190'),
    ('-2E+2', '200'),
    ('12.340', '12.34'),
    ('0.5', '0.5'),
  ],
)
async def test_order_quantity_is_sent_positionally(
  scope: str,
  kind: Literal['MARKET', 'LIMIT', 'POST_ONLY'],
  qty: str,
  expected: str,
  monkeypatch: pytest.MonkeyPatch,
):
  """Step-rounded sizes arrive normalized (`190` is `1.9E+2`); the venue rejects exponent form."""
  endpoint = AsyncMock(return_value={'orderId': 123})
  monkeypatch.setattr(
    PerpOrders if scope == 'perp' else SpotOrders, 'place_order', endpoint
  )
  order: Order = {'type': kind, 'qty': Decimal(qty), 'price': Decimal('0.2448')}
  await market(scope).place_order(order)
  assert endpoint.await_args is not None
  assert sent_params(scope, endpoint.await_args.args[0])['quantity'] == expected


@pytest.mark.parametrize('scope', ['spot', 'perp'])
@pytest.mark.parametrize(
  ('price', 'expected'),
  [
    ('1.2E+2', '120'),
    ('1E+5', '100000'),
    ('0.24480', '0.2448'),
    ('0.0000095', '0.0000095'),
  ],
)
async def test_limit_price_is_sent_positionally(
  scope: str, price: str, expected: str, monkeypatch: pytest.MonkeyPatch
):
  """Tick-rounded prices arrive normalized too (`120` is `1.2E+2`)."""
  endpoint = AsyncMock(return_value={'orderId': 123})
  monkeypatch.setattr(
    PerpOrders if scope == 'perp' else SpotOrders, 'place_order', endpoint
  )
  order: Order = {'type': 'LIMIT', 'qty': Decimal('5'), 'price': Decimal(price)}
  await market(scope).place_order(order)
  assert endpoint.await_args is not None
  assert sent_params(scope, endpoint.await_args.args[0])['price'] == expected


@pytest.mark.parametrize('scope', ['spot', 'perp'])
async def test_only_documented_not_found_is_none(
  scope: str, monkeypatch: pytest.MonkeyPatch
):
  """Authentication and unrelated bad requests must remain SDK failures."""
  endpoint = AsyncMock(
    side_effect=[
      ClientBadRequest(400, {'code': -2013, 'msg': 'Order does not exist'}),
      ClientBadRequest(400, {'code': -1100, 'msg': 'Illegal parameter'}),
      ClientAuthError('invalid agent'),
    ]
  )
  monkeypatch.setattr(PerpQuery if scope == 'perp' else SpotQuery, 'order', endpoint)
  target = market(scope)
  assert await target.query_order('123') is None
  with pytest.raises(BadRequest):
    await target.query_order('123')
  with pytest.raises(AuthError):
    await target.query_order('123')


async def test_batch_boundary_retains_partial_errors(monkeypatch: pytest.MonkeyPatch):
  """The eleven-order path makes two requests and does not hide batch errors."""
  results = [{'orderId': n} for n in range(10)] + [
    {'code': -2011, 'msg': 'Unknown order'}
  ]
  endpoint = AsyncMock(side_effect=[results[:10], results[10:]])
  monkeypatch.setattr(CancelBatchOrders, 'cancel_batch_orders', endpoint)
  target = market('perp')
  assert await target.cancel_orders([str(n) for n in range(11)]) == results
  assert [c.args[0]['orderIdList'] for c in endpoint.await_args_list] == [
    list(range(10)),
    [10],
  ]
  assert await target.cancel_orders([]) == []
  assert endpoint.await_count == 2


@pytest.mark.parametrize('scope', ['spot', 'perp'])
async def test_ioc_setting_sends_limit_ioc(scope: str, monkeypatch: pytest.MonkeyPatch):
  """`time_in_force: IOC` turns a LIMIT order immediate-or-cancel, price kept."""
  endpoint = AsyncMock(return_value={'orderId': 123})
  monkeypatch.setattr(
    PerpOrders if scope == 'perp' else SpotOrders, 'place_order', endpoint
  )
  order: Order = {'type': 'LIMIT', 'qty': Decimal('-2'), 'price': '0.75'}
  placed = await market(scope).place_order(
    order, settings={'aster': {'time_in_force': 'IOC'}}
  )
  assert endpoint.await_args is not None
  request = endpoint.await_args.args[0]
  assert placed.id == '123'
  assert request['type'] == 'LIMIT' and request['side'] == 'SELL'
  assert request['timeInForce'] == 'IOC'
  assert request['price'] == Decimal('0.75')
  assert sent_params(scope, request)['timeInForce'] == 'IOC'


@pytest.mark.parametrize('scope', ['spot', 'perp'])
@pytest.mark.parametrize('kind', ['MARKET', 'POST_ONLY'])
async def test_ioc_setting_rejects_other_order_types(
  scope: str,
  kind: Literal['MARKET', 'POST_ONLY'],
  monkeypatch: pytest.MonkeyPatch,
):
  """The setting applies to LIMIT only; elsewhere it raises before anything is sent."""
  endpoint = AsyncMock(return_value={'orderId': 123})
  monkeypatch.setattr(
    PerpOrders if scope == 'perp' else SpotOrders, 'place_order', endpoint
  )
  order: Order = {'type': kind, 'qty': Decimal('1'), 'price': '0.75'}
  with pytest.raises(ValueError, match='LIMIT orders only'):
    await market(scope).place_order(order, settings={'aster': {'time_in_force': 'IOC'}})
  endpoint.assert_not_awaited()


async def test_other_venues_settings_are_ignored(monkeypatch: pytest.MonkeyPatch):
  """One settings dict can serve every venue: only the `aster` key is read."""
  endpoint = AsyncMock(return_value={'orderId': 123})
  monkeypatch.setattr(PerpOrders, 'place_order', endpoint)
  order: Order = {'type': 'LIMIT', 'qty': Decimal('1'), 'price': '0.75'}
  await market('perp').place_order(
    order, settings={'hyperliquid': {'limit_tif': 'Ioc'}}
  )
  assert endpoint.await_args is not None
  assert endpoint.await_args.args[0]['timeInForce'] == 'GTC'


async def test_cancel_rejects_aster_settings():
  """No Aster setting applies to cancellation."""
  with pytest.raises(NotImplementedError):
    await market('perp').cancel_order('1', settings={'aster': {'time_in_force': 'IOC'}})
