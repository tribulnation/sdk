"""SDK order ids on pushed fills, and orders placed with a client order id."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing_extensions import Any, cast
from unittest.mock import AsyncMock
import uuid

import pytest
from typed_dydx.indexer.schemas import Order as IndexerOrder, PerpetualMarket
from typed_dydx.protos.dydxprotocol import clob, subaccounts

from tribulnation.dydx.market.exchange import Exchange
from tribulnation.dydx.market.impl.mixin import MarketMixin
from tribulnation.dydx.market.impl.orders import (
  INDEXER_NAMESPACE,
  parse_state,
  place_order,
  serialize_id,
  subaccount_numbers,
)
from tribulnation.dydx.market.impl.trades import trades_stream
from tribulnation.sdk.market import Order

ADDRESS = 'dydx1039f5sxkl0t39vxcsnmlu62ly22typdap0zkyn'
"""The address of typed-dev's recorded `parent_subaccounts` messages."""
SUBACCOUNT_0 = 'c2b49dd5-8487-502a-9364-ebda4f356ac0'
"""The indexer's id of its subaccount 0, as recorded."""
SUBACCOUNT_128 = str(uuid.uuid5(INDEXER_NAMESPACE, f'{ADDRESS}-128'))
"""The indexer's id of its first child subaccount."""
TIME = datetime(2026, 3, 15, 8, 28, 41, tzinfo=timezone.utc)
MARKET = cast(PerpetualMarket, {'ticker': 'XMR-USD'})


def sdk_id(*, client_id: int, flags: int, number: int) -> str:
  """The SDK id of an XMR-USD (CLOB pair 94) order."""
  return serialize_id(
    clob.OrderId(
      client_id=client_id,
      order_flags=flags,
      clob_pair_id=94,
      subaccount_id=subaccounts.SubaccountId(owner=ADDRESS, number=number),
    )
  )


def pushed_order(
  id: str, *, subaccount: str, client_id: int, flags: int | None
) -> dict[str, Any]:
  """A pushed order: the indexer's subaccount id, no subaccount number."""
  row: dict[str, Any] = {
    'id': id,
    'subaccountId': subaccount,
    'clientId': client_id,
    'clobPairId': 94,
    'side': 'SELL',
    'size': Decimal('0.27'),
    'status': 'FILLED',
    'timeInForce': 'GTT',
    'type': 'LIMIT',
    'ticker': 'XMR-USD',
  }
  if flags is not None:
    row['orderFlags'] = flags
  return row


def pushed_fill(
  id: str, order_id: str | None, *, ticker: str = 'XMR-USD'
) -> dict[str, Any]:
  """A pushed fill, naming its order by indexer id when it has one."""
  row: dict[str, Any] = {
    'id': id,
    'ticker': ticker,
    'side': 'SELL',
    'price': Decimal('356.9'),
    'size': Decimal('0.27'),
    'createdAt': TIME,
    'liquidity': 'TAKER',
    'type': 'LIMIT' if order_id else 'LIQUIDATED',
  }
  if order_id is not None:
    row['orderId'] = order_id
  return row


def test_subaccount_numbers_by_indexer_id():
  """Subaccount 0 maps from its recorded indexer id; children follow every 128."""
  numbers = subaccount_numbers(ADDRESS, 0)
  assert numbers[SUBACCOUNT_0] == 0 and numbers[SUBACCOUNT_128] == 128
  assert sorted(numbers.values())[:3] == [0, 128, 256]
  assert max(numbers.values()) == 128_000
  assert min(subaccount_numbers(ADDRESS, 3).values()) == 3


async def test_stream_fills_carry_the_sdk_id_of_their_pushed_order(
  monkeypatch: pytest.MonkeyPatch,
):
  """Orders in the fill's message give its SDK id, on the parent and a child, the one
  `OrderState.id` reports; fills without an order, or whose order is absent or
  unidentifiable, have none."""
  messages: list[dict[str, Any]] = [
    {
      'orders': [
        pushed_order(
          '70c72898-7ba8-5199-acdf-c7a07c85a7d3',
          subaccount=SUBACCOUNT_0,
          client_id=32124288,
          flags=0,
        )
      ],
      'fills': [
        pushed_fill('parent', '70c72898-7ba8-5199-acdf-c7a07c85a7d3'),
        pushed_fill(
          'other-market', '70c72898-7ba8-5199-acdf-c7a07c85a7d3', ticker='BTC-USD'
        ),
      ],
    },
    {'orders': [pushed_order('o2', subaccount=SUBACCOUNT_0, client_id=1, flags=64)]},
    {
      'orders': [pushed_order('o3', subaccount=SUBACCOUNT_128, client_id=5, flags=64)],
      'fills': [pushed_fill('child', 'o3')],
    },
    {'fills': [pushed_fill('liquidated', None)]},
    {'orders': [], 'fills': [pushed_fill('absent', 'o2')]},
    {
      'orders': [pushed_order('o6', subaccount=SUBACCOUNT_0, client_id=6, flags=None)],
      'fills': [pushed_fill('no-flags', 'o6')],
    },
  ]

  @asynccontextmanager
  async def subscribe(*args: Any, **kwargs: Any):
    """Push the fixture messages."""

    async def pushed():
      """Each message's contents."""
      for message in messages:
        yield message

    yield pushed()

  monkeypatch.setattr(MarketMixin, 'subscribe_parent_subaccount', subscribe)
  market = MarketMixin(
    shared=Exchange.new(address=ADDRESS, public=True).shared, perpetual_market=MARKET
  )
  async with trades_stream(market) as stream:
    trades = [t async for t in stream]
  assert {t.id: t.order_id for t in trades} == {
    'parent': sdk_id(client_id=32124288, flags=0, number=0),
    'child': sdk_id(client_id=5, flags=64, number=128),
    'liquidated': None,
    'absent': None,
    'no-flags': None,
  }
  assert all(t.client_order_id is None for t in trades)
  listed: dict[str, Any] = {
    **messages[0]['orders'][0],
    'price': Decimal('356.9'),
    'totalFilled': Decimal('0.27'),
    'subaccountNumber': 0,
  }
  state = parse_state(cast(IndexerOrder, listed), address=ADDRESS)
  assert state.id == trades[0].order_id


@pytest.mark.parametrize('kind', ['LIMIT', 'POST_ONLY', 'MARKET'])
async def test_client_order_id_leaves_the_order_unchanged(
  monkeypatch: pytest.MonkeyPatch, kind: Any
):
  """The protocol client id is part of the order id and generated by the client, so a
  caller's client order id is ignored."""
  order_id = clob.OrderId(
    client_id=7,
    order_flags=64,
    clob_pair_id=94,
    subaccount_id=subaccounts.SubaccountId(owner=ADDRESS, number=0),
  )
  exchange = Exchange.new(address=ADDRESS, public=True)
  node = AsyncMock(
    return_value=SimpleNamespace(order=SimpleNamespace(order_id=order_id))
  )
  monkeypatch.setattr(type(exchange.client.node), 'place_order', node)
  market = MarketMixin(shared=exchange.shared, perpetual_market=MARKET)
  order: Order = {'qty': '-0.27', 'price': '356.9', 'type': kind}
  plain = await place_order(market, order)
  tagged = await place_order(market, {**order, 'client_order_id': 'my-order'})
  first, second = node.await_args_list
  assert first == second
  assert plain.id == tagged.id == serialize_id(order_id)
