"""Client order IDs reach `orderLinkId`, and fills report the order they executed."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing_extensions import Any, AsyncIterator, Literal, cast

import pytest
from typed_bybit import Bybit
from typed_bybit.private.execution import ExecutionUpdate
from typed_bybit.trade.create_order import (
  CreateLimitOrderRequest,
  CreateMarketOrderRequest,
  CreateOrderResult,
)
from typed_bybit.trade.trade_history import Execution, TradeHistoryResult

from tribulnation.bybit.market import PerpMarket, SpotMarket
from tribulnation.bybit.market.impl import Cache, MarketMixin
from tribulnation.bybit.market.impl.streams import trades_stream
from tribulnation.sdk.market import Order, Trade

START = datetime(2025, 7, 20, tzinfo=timezone.utc)
END = datetime(2025, 7, 21, tzinfo=timezone.utc)
LINK_ID = 'grid-7_leg-2'


def execution(order_link_id: str) -> Execution:
  """One linear fill as `trade.trade_history` reports it."""
  return {
    'symbol': 'BTCUSDT',
    'orderId': '1f1a8b6c-2d44-4e6f-9a3b-5c1d2e3f4a5b',
    'orderLinkId': order_link_id,
    'side': 'Sell',
    'orderPrice': Decimal('65000'),
    'orderQty': Decimal('0.01'),
    'leavesQty': Decimal('0'),
    'orderType': 'Limit',
    'stopOrderType': '',
    'execFee': Decimal('0.13'),
    'execId': 'c4f2d1e0-7b6a-5c4d-3e2f-1a0b9c8d7e6f',
    'execPrice': Decimal('65000'),
    'execQty': Decimal('0.01'),
    'execType': 'Trade',
    'execValue': Decimal('650'),
    'execTime': START,
    'feeCurrency': 'USDT',
    'isMaker': True,
    'feeRate': Decimal('0.0002'),
    'blockTradeId': '',
    'closedSize': Decimal('0'),
    'seq': 17920359745,
  }


def execution_update(order_link_id: str) -> ExecutionUpdate:
  """That fill as the private `execution` stream pushes it."""
  return {
    'category': 'linear',
    'symbol': 'BTCUSDT',
    'isLeverage': '0',
    'orderId': '1f1a8b6c-2d44-4e6f-9a3b-5c1d2e3f4a5b',
    'orderLinkId': order_link_id,
    'side': 'Sell',
    'orderPrice': Decimal('65000'),
    'orderQty': Decimal('0.01'),
    'leavesQty': Decimal('0'),
    'orderType': 'Limit',
    'stopOrderType': '',
    'execFee': Decimal('0.13'),
    'execId': 'c4f2d1e0-7b6a-5c4d-3e2f-1a0b9c8d7e6f',
    'execPrice': Decimal('65000'),
    'execQty': Decimal('0.01'),
    'execType': 'Trade',
    'execValue': Decimal('650'),
    'execTime': START,
    'isMaker': True,
    'feeRate': Decimal('0.0002'),
    'blockTradeId': '',
    'closedSize': Decimal('0'),
    'seq': 17920359745,
    'feeCurrency': 'USDT',
  }


@dataclass
class FakeTrade:
  """A `trade` endpoint recording placements and serving one history page."""

  requests: list[CreateMarketOrderRequest | CreateLimitOrderRequest] = field(
    default_factory=list[CreateMarketOrderRequest | CreateLimitOrderRequest]
  )
  fills: list[Execution] = field(default_factory=list[Execution])

  async def create_order(
    self,
    request: CreateMarketOrderRequest | CreateLimitOrderRequest,
    **kwargs: Any,
  ) -> CreateOrderResult:
    """Record the request and acknowledge it."""
    self.requests.append(request)
    return {'orderId': '1f1a8b6c', 'orderLinkId': request.get('orderLinkId', '')}

  async def trade_history(self, category: str, **kwargs: Any) -> TradeHistoryResult:
    """Serve the fixture fills as the only page."""
    return {'category': 'linear', 'list': self.fills}


@dataclass
class FakeClient:
  """Just enough of `Bybit` for placement and trade history."""

  trade: FakeTrade = field(default_factory=FakeTrade)


@pytest.mark.parametrize('category', ['spot', 'linear'])
@pytest.mark.parametrize('kind', ['MARKET', 'LIMIT', 'POST_ONLY'])
@pytest.mark.parametrize('client_order_id', [LINK_ID, None])
async def test_place_order_order_link_id(
  category: Literal['spot', 'linear'],
  kind: Literal['MARKET', 'LIMIT', 'POST_ONLY'],
  client_order_id: str | None,
):
  """`orderLinkId` carries the ID unchanged, and is absent when none is given."""
  client = FakeClient()
  cls = SpotMarket if category == 'spot' else PerpMarket
  market = cls(client=cast(Bybit, client), cache=Cache(), symbol='BTCUSDT')
  order: Order = {'type': kind, 'qty': Decimal('0.5'), 'price': Decimal('65000')}
  if client_order_id is not None:
    order['client_order_id'] = client_order_id
  placed = await market.place_order(order)
  assert placed.id == '1f1a8b6c'
  expected: dict[str, Any] = {
    'category': category,
    'symbol': 'BTCUSDT',
    'side': 'Buy',
    'qty': '0.5',
  }
  if kind == 'MARKET':
    expected |= {'orderType': 'Market', 'timeInForce': 'IOC'}
  else:
    expected |= {
      'orderType': 'Limit',
      'price': '65000',
      'timeInForce': 'PostOnly' if kind == 'POST_ONLY' else 'GTC',
    }
  if client_order_id is not None:
    expected['orderLinkId'] = client_order_id
  assert client.trade.requests == [expected]


@pytest.mark.parametrize(('link_id', 'expected'), [(LINK_ID, LINK_ID), ('', None)])
async def test_trades_history_order_ids(link_id: str, expected: str | None):
  """History fills map `orderId`, and an empty `orderLinkId` reads as absent."""
  client = FakeClient(trade=FakeTrade(fills=[execution(link_id)]))
  market = PerpMarket(client=cast(Bybit, client), cache=Cache(), symbol='BTCUSDT')
  trades = await market.trades_history(START, END)
  assert [(t.order_id, t.client_order_id) for t in trades] == [
    ('1f1a8b6c-2d44-4e6f-9a3b-5c1d2e3f4a5b', expected)
  ]


@pytest.mark.parametrize(('link_id', 'expected'), [(LINK_ID, LINK_ID), ('', None)])
async def test_trades_stream_order_ids(link_id: str, expected: str | None):
  """Streamed fills map `orderId`, and an empty `orderLinkId` reads as absent."""

  @asynccontextmanager
  async def subscribe_executions(**_: Any) -> AsyncIterator[AsyncIterator[Any]]:
    """Yield one fill for this market and one for another symbol."""

    async def gen() -> AsyncIterator[ExecutionUpdate]:
      """Replay the fixture executions."""
      yield {**execution_update(link_id), 'symbol': 'ETHUSDT'}
      yield execution_update(link_id)

    yield gen()

  market = cast(
    MarketMixin,
    SimpleNamespace(
      category='linear', symbol='BTCUSDT', subscribe_executions=subscribe_executions
    ),
  )
  async with trades_stream(market) as stream:
    trades: list[Trade] = [t async for t in stream]
  assert [(t.order_id, t.client_order_id) for t in trades] == [
    ('1f1a8b6c-2d44-4e6f-9a3b-5c1d2e3f4a5b', expected)
  ]
