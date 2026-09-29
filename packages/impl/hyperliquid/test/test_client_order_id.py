"""Client order IDs reach the order wire, and fills report the order they executed."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing_extensions import Any, AsyncIterator, cast
from unittest.mock import AsyncMock, Mock

import pytest
from typed_core import PaginatedResponse
from typed_hyperliquid import Hyperliquid
from typed_hyperliquid.exchange.order import PlaceOrderOk
from typed_hyperliquid.info.user_fills_by_time import UserFill
from typed_hyperliquid.streams.user_fills import UserFill as StreamFill, UserFills

from tribulnation.hyperliquid.market.impl import trades
from tribulnation.hyperliquid.market.impl.mixin import PerpMarketMixin, Shared
from tribulnation.hyperliquid.market.impl.orders import place_order
from tribulnation.hyperliquid.market.perps_exchange import PerpExchange
from tribulnation.sdk.market import Order, Trade

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = START + timedelta(days=1)
CLOID = '0x1234567890abcdef1234567890abcdef'


def with_cloid(fill: UserFill | StreamFill, cloid: str | None) -> Any:
  """Add the `cloid` the venue sends on fills of orders placed with one.

  typed-hyperliquid does not declare the key, but its validation keeps it.
  """
  if cloid is not None:
    cast(dict[str, object], fill)['cloid'] = cloid
  return fill


def rest_fill(
  *, oid: int, tid: int, coin: str = 'BTC', cloid: str | None = None
) -> UserFill:
  """Build a `userFillsByTime` row as the typed client parses it."""
  fill: UserFill = {
    'coin': coin,
    'px': Decimal('65000'),
    'sz': Decimal('0.01'),
    'side': 'B',
    'time': START,
    'startPosition': Decimal('0'),
    'dir': 'Open Long',
    'closedPnl': Decimal('0'),
    'hash': '0xa166e3fa63c25663024b03f2e0da011a00307e4017465df020210d3d432e7cb8',
    'oid': oid,
    'crossed': False,
    'fee': Decimal('0.1'),
    'tid': tid,
    'feeToken': 'USDC',
    'twapId': None,
  }
  return with_cloid(fill, cloid)


async def resolve_asset_index(name: str) -> str:
  """Resolve the fixture's fee token without a metadata request."""
  return '0'


@pytest.mark.parametrize('client_order_id', [CLOID, None])
async def test_place_order_cloid(client_order_id: str | None):
  """The cloid goes to the native `c` key unchanged, and is absent when not given."""
  result: PlaceOrderOk = {
    'status': 'ok',
    'response': {
      'type': 'order',
      'data': {'statuses': [{'resting': {'oid': 77, 'cloid': CLOID}}]},
    },
  }
  order_endpoint = AsyncMock(return_value=result)
  market = cast(
    PerpMarketMixin,
    SimpleNamespace(
      asset_id=3, client=SimpleNamespace(exchange=SimpleNamespace(order=order_endpoint))
    ),
  )
  order: Order = {'qty': Decimal('-2'), 'price': Decimal('10'), 'type': 'POST_ONLY'}
  if client_order_id is not None:
    order['client_order_id'] = client_order_id

  response = await place_order(market, order)

  assert response.id == '77'
  expected: dict[str, Any] = {
    'a': 3,
    'b': False,
    'p': Decimal('10'),
    's': Decimal('2'),
    'r': False,
    't': {'limit': {'tif': 'Alo'}},
  }
  if client_order_id is not None:
    expected['c'] = client_order_id
  order_endpoint.assert_awaited_once_with(orders=[expected], grouping='na')


async def test_trades_history_order_ids():
  """History fills carry the placement's `oid`, and its `cloid` when it had one."""

  async def fetch(state: int) -> tuple[list[UserFill], None]:
    """Serve one page with this market's fills and another coin's."""
    return [
      rest_fill(oid=77, tid=1, cloid=CLOID),
      rest_fill(oid=78, tid=2, coin='ETH'),
      rest_fill(oid=79, tid=3),
    ], None

  async def call(fn: Any) -> Any:
    """Run the request directly, without the SDK's retry wrapper."""
    return await fn()

  market = cast(
    PerpMarketMixin,
    SimpleNamespace(
      client=SimpleNamespace(
        info=SimpleNamespace(
          user_fills_by_time_paged=Mock(return_value=PaginatedResponse(0, fetch))
        )
      ),
      asset_name='BTC',
      address='0xfixture',
      call_hyperliquid=call,
      shared=SimpleNamespace(resolve_asset_index=resolve_asset_index),
    ),
  )
  pages = [page async for page in trades.trades_history(market, START, END)]
  assert [(t.id, t.order_id, t.client_order_id) for t in pages[0]] == [
    ('1', '77', CLOID),
    ('3', '79', None),
  ]


async def test_trades_stream_order_ids():
  """Streamed fills carry `oid` and any `cloid`; the snapshot is skipped."""
  fill: StreamFill = {
    'coin': 'BTC',
    'px': Decimal('65000'),
    'sz': Decimal('0.01'),
    'side': 'A',
    'time': START,
    'startPosition': Decimal('0.01'),
    'dir': 'Close Long',
    'closedPnl': Decimal('1'),
    'hash': '0xa166e3fa63c25663024b03f2e0da011a00307e4017465df020210d3d432e7cb8',
    'oid': 90542681,
    'crossed': True,
    'fee': Decimal('0.1'),
    'tid': 118906512037719,
    'feeToken': 'USDC',
  }
  chunks: list[UserFills] = [
    {'fills': [{**fill, 'oid': 1}], 'isSnapshot': True, 'user': '0xfixture'},
    {
      'fills': [with_cloid({**fill}, CLOID), {**fill, 'oid': 2}],
      'isSnapshot': False,
      'user': '0xfixture',
    },
  ]

  @asynccontextmanager
  async def subscribe_user_fills(**_: Any) -> AsyncIterator[AsyncIterator[UserFills]]:
    """Yield the fixture chunks as one subscription."""

    async def gen() -> AsyncIterator[UserFills]:
      """Replay the fixture chunks."""
      for chunk in chunks:
        yield chunk

    yield gen()

  market = cast(
    PerpMarketMixin,
    SimpleNamespace(
      asset_name='BTC',
      subscribe_user_fills=subscribe_user_fills,
      shared=SimpleNamespace(resolve_asset_index=resolve_asset_index),
    ),
  )
  async with trades.trades_stream(market) as stream:
    rows: list[Trade] = [trade async for trade in stream]
  assert [(t.id, t.order_id, t.client_order_id) for t in rows] == [
    ('118906512037719', '90542681', CLOID),
    ('118906512037719', '2', None),
  ]


async def test_exchange_history_order_ids(monkeypatch: pytest.MonkeyPatch):
  """Exchange-wide fills carry the placement's `oid` and any `cloid`."""

  async def fetch(state: int) -> tuple[list[UserFill], None]:
    """Serve one page of this DEX's fills."""
    return [rest_fill(oid=77, tid=1, cloid=CLOID), rest_fill(oid=78, tid=2)], None

  monkeypatch.setattr(
    Shared, 'resolve_asset_index', AsyncMock(side_effect=resolve_asset_index)
  )
  async with Hyperliquid.new(public=True) as client:
    monkeypatch.setattr(
      type(client.info),
      'user_fills_by_time_paged',
      Mock(return_value=PaginatedResponse(0, fetch)),
    )
    exchange = PerpExchange(
      shared=Shared(client=client, maybe_address='0xfixture'), dex=None
    )
    rows = await exchange.trades_history(None, START, END)
  assert [(t.id, t.order_id, t.client_order_id) for t in rows] == [
    ('1', '77', CLOID),
    ('2', '78', None),
  ]
