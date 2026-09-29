"""Client order IDs reach the native request, and fills report the order they executed."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import re

import pytest
from typed_aster.futures.trade.place_order import PlaceOrder as PerpOrders
from typed_aster.futures.user_stream.events import OrderTradeUpdate, OrderUpdate
from typed_aster.schemas import ExecutionReport
from typed_aster.spot.trade.place_order import PlaceOrder as SpotOrders
from typing_extensions import Any, AsyncIterator, Literal

from tribulnation.aster import AsterMarket
from tribulnation.aster.core import Scope
from tribulnation.aster.market.markets import PerpMarket, SpotMarket
from tribulnation.aster.market.streams import perp_fills, spot_fills
from tribulnation.sdk.market import Order, Trade

TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def market(scope: Scope) -> SpotMarket | PerpMarket:
  """A testnet market over a public client, without catalogue requests."""
  shared = AsterMarket.new(public=True, mainnet=False).shared
  cls = PerpMarket if scope == 'perp' else SpotMarket
  return cls(shared=shared, symbol='ASTERUSDT')


@pytest.mark.parametrize('scope', ['spot', 'perp'])
@pytest.mark.parametrize('kind', ['MARKET', 'LIMIT', 'POST_ONLY'])
@pytest.mark.parametrize('client_order_id', ['bot-1:leg/A_2.x', None])
async def test_place_order_client_order_id(
  scope: Scope,
  kind: Literal['MARKET', 'LIMIT', 'POST_ONLY'],
  client_order_id: str | None,
  monkeypatch: pytest.MonkeyPatch,
):
  """`newClientOrderId` carries the ID unchanged, and is absent when none is given."""
  endpoint = AsyncMock(return_value={'orderId': 123})
  monkeypatch.setattr(
    PerpOrders if scope == 'perp' else SpotOrders, 'place_order', endpoint
  )
  order: Order = {'type': kind, 'qty': Decimal('-5'), 'price': '0.75'}
  order['client_order_id'] = client_order_id
  await market(scope).place_order(order)
  assert endpoint.await_args is not None
  request = endpoint.await_args.args[0]
  expected: dict[str, Any] = {
    'symbol': 'ASTERUSDT',
    'side': 'SELL',
    'quantity': Decimal('5'),
  }
  if kind == 'MARKET':
    expected['type'] = 'MARKET'
  else:
    expected |= {
      'type': 'LIMIT',
      'price': Decimal('0.75'),
      'timeInForce': 'GTX' if kind == 'POST_ONLY' else 'GTC',
    }
  if scope == 'perp':
    expected['newOrderRespType'] = 'RESULT'
  if client_order_id is not None:
    expected['newClientOrderId'] = client_order_id
  assert request == expected


def perp_update(client_order_id: str) -> OrderTradeUpdate:
  """A perpetual `ORDER_TRADE_UPDATE` for one partial fill."""
  order: OrderUpdate = {
    's': 'BTCUSDT',
    'c': client_order_id,
    'S': 'BUY',
    'o': 'LIMIT',
    'f': 'GTC',
    'q': Decimal('0.01'),
    'p': Decimal('65000'),
    'ap': Decimal('65000'),
    'sp': Decimal('0'),
    'x': 'TRADE',
    'X': 'PARTIALLY_FILLED',
    'i': 8886774,
    'l': Decimal('0.004'),
    'z': Decimal('0.004'),
    'L': Decimal('65000'),
    'N': 'USDT',
    'n': Decimal('0.052'),
    'T': TIME,
    't': 1216,
    'm': True,
    'R': False,
    'ot': 'LIMIT',
    'ps': 'BOTH',
    'rp': Decimal('0'),
  }
  return {'e': 'ORDER_TRADE_UPDATE', 'E': TIME, 'T': TIME, 'o': order}


def spot_report(client_order_id: str) -> ExecutionReport:
  """A spot `executionReport` for one partial fill."""
  return {
    'e': 'executionReport',
    'E': TIME,
    's': 'ASTERUSDT',
    'ba': 'ASTER',
    'qa': 'USDT',
    'c': client_order_id,
    'S': 'SELL',
    'o': 'LIMIT',
    'f': 'GTC',
    'q': Decimal('20'),
    'p': Decimal('0.75'),
    'ap': Decimal('0.75'),
    'P': Decimal('0'),
    'x': 'TRADE',
    'X': 'PARTIALLY_FILLED',
    'i': 4471,
    'l': Decimal('5'),
    'z': Decimal('5'),
    'L': Decimal('0.75'),
    'n': Decimal('0.00375'),
    'N': 'USDT',
    'T': TIME,
    't': 902,
    'm': False,
    'ot': 'LIMIT',
    'O': TIME,
    'Z': Decimal('3.75'),
    'Y': Decimal('3.75'),
    'Q': Decimal('0'),
    'u': TIME,
    'h': '0x5f2c',
  }


@pytest.mark.parametrize(
  ('client_order_id', 'expected'), [('bot-1:leg/A_2.x', 'bot-1:leg/A_2.x'), ('', None)]
)
async def test_perp_fill_order_ids(client_order_id: str, expected: str | None):
  """Perpetual fills map `i` and `c`, with an empty client ID read as absent."""

  async def events() -> AsyncIterator[OrderTradeUpdate]:
    """Replay one native trade update."""
    yield perp_update(client_order_id)

  fills: list[tuple[str, Trade]] = [row async for row in perp_fills(events())]
  assert [(s, t.id, t.order_id, t.client_order_id) for s, t in fills] == [
    ('BTCUSDT', '1216', '8886774', expected)
  ]


@pytest.mark.parametrize(
  ('client_order_id', 'expected'),
  [('web_6gCrw2kRUAF9', 'web_6gCrw2kRUAF9'), ('', None)],
)
async def test_spot_fill_order_ids(client_order_id: str, expected: str | None):
  """Spot fills map `i` and `c`, with an empty client ID read as absent."""

  async def events() -> AsyncIterator[ExecutionReport]:
    """Replay one native execution report."""
    yield spot_report(client_order_id)

  fills: list[tuple[str, Trade]] = [row async for row in spot_fills(events())]
  assert [(s, t.id, t.order_id, t.client_order_id) for s, t in fills] == [
    ('ASTERUSDT', '902', '4471', expected)
  ]


@pytest.mark.parametrize('scope', ['spot', 'perp'])
def test_random_client_order_id_generates_hex(scope: Scope):
  """Fresh IDs are 32 hex digits, within `newClientOrderId`'s 36 characters."""
  target = market(scope)
  ids = {target.random_client_order_id() for _ in range(100)}
  assert len(ids) == 100
  assert all(re.fullmatch(r'[0-9a-f]{32}', value) for value in ids)
