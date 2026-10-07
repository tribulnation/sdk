"""Lighter books carry the WS `last_updated_at`; REST snapshots have no time."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from typed_core.validation import validator
from typed_lighter.streams.order_book import OrderBookUpdate
from typing_extensions import Any, cast

from tribulnation.lighter.core import Shared
from tribulnation.lighter.market import books

MARKET = 1
TIME_US = 1791370594322123
TIME = datetime(2026, 10, 7, 10, 56, 34, 322123, tzinfo=timezone.utc)


def frame(
  kind: str, *, us: int, begin: int, nonce: int, bids: list[Any], asks: list[Any]
) -> dict[str, Any]:
  """A raw `order_book` frame, as Lighter sends it."""
  return {
    'type': f'{kind}/order_book',
    'channel': f'order_book:{MARKET}',
    'order_book': {
      'code': 0,
      'asks': asks,
      'bids': bids,
      'offset': nonce,
      'nonce': nonce,
      'begin_nonce': begin,
      'last_updated_at': us,
    },
    'offset': nonce,
    'last_updated_at': us,
    'timestamp': us // 1000 + 3,
  }


def frames() -> list[dict[str, Any]]:
  """A snapshot then a delta one second later that moves the best bid."""
  return [
    frame(
      'subscribed',
      us=TIME_US,
      begin=0,
      nonce=10,
      bids=[{'price': '100', 'size': '1'}],
      asks=[{'price': '101', 'size': '2'}],
    ),
    frame(
      'update',
      us=TIME_US + 1_000_000,
      begin=10,
      nonce=11,
      bids=[{'price': '100.5', 'size': '3'}],
      asks=[],
    ),
  ]


def unvalidated(row: dict[str, Any]) -> dict[str, Any]:
  """The frame with decimal levels but a raw `last_updated_at`."""
  state = row['order_book']
  return row | {
    'order_book': state
    | {
      side: [
        {'price': Decimal(lvl['price']), 'size': Decimal(lvl['size'])}
        for lvl in state[side]
      ]
      for side in ('bids', 'asks')
    }
  }


class Stream:
  """A native `order_book` stream replaying fixture frames."""

  def __init__(self, rows: list[Any]):
    self.rows = rows

  def __aiter__(self):
    """Yield the fixture frames."""
    return self.iterate()

  async def iterate(self):
    """Yield each frame in order."""
    for row in self.rows:
      yield row

  async def unsubscribe(self):
    """Nothing to release."""


@pytest.mark.parametrize('validate', [True, False])
async def test_stream_time_advances(validate: bool):
  """The snapshot's time is set, and each delta advances the maintained book's time."""
  rows = [
    validator(OrderBookUpdate).python(f) if validate else unvalidated(f)
    for f in frames()
  ]

  async def order_book(market_id: int):
    """Open the fixture stream."""
    assert market_id == MARKET
    return Stream(rows)

  shared = SimpleNamespace(
    books={}, client=SimpleNamespace(streams=SimpleNamespace(order_book=order_book))
  )
  ctx = await books.subscription(cast(Shared, shared), MARKET).subscribe_stream()
  out = [book async for book in ctx.iterator]
  assert [b.time for b in out] == [TIME, TIME + timedelta(seconds=1)]
  assert out[-1].best_bid.price == Decimal('100.5')
  assert out[-1].best_ask.price == Decimal('101')


async def test_rest_depth_has_no_time():
  """`orderBookOrders` has no snapshot timestamp, so REST books carry None."""
  order: dict[str, Any] = {
    'order_index': 1,
    'order_id': '1',
    'owner_account_index': 1,
    'initial_base_amount': Decimal(1),
    'remaining_base_amount': Decimal(1),
    'order_expiry': datetime.now(timezone.utc),
    'transaction_time': TIME,
  }

  async def order_book_orders(*, market_id: int, limit: int) -> dict[str, Any]:
    """Return one resting order per side."""
    assert market_id == MARKET
    return {
      'code': 200,
      'total_bids': 1,
      'bids': [order | {'price': Decimal(100)}],
      'total_asks': 1,
      'asks': [order | {'price': Decimal(101)}],
    }

  async def call(fn: Any):
    """Run the request directly."""
    return await fn()

  shared = SimpleNamespace(
    call=call,
    client=SimpleNamespace(
      api=SimpleNamespace(markets=SimpleNamespace(order_book_orders=order_book_orders))
    ),
  )
  book = await books.depth(cast(Shared, shared), MARKET)
  assert book.best_bid.price == Decimal(100)
  assert book.time is None
