"""Both Coinbase WebSocket channels are incremental, and the fold must sit upstream.

A `Subscription` fans one upstream out to many subscribers, and a subscriber that joins
late never sees the frames that came before it. Folding downstream of the fan-out hands
a late subscriber a book built from deltas alone -- missing the snapshot -- and no live
check notices, because the first subscriber's book is correct.
"""

from typing_extensions import Any, AsyncIterable, Literal, cast
from datetime import datetime, timezone
from decimal import Decimal
import asyncio

from typed_coinbase import Coinbase
from typed_coinbase.app.advanced_trade.streams.market_data.level2 import (
  Level2Message,
  Level2Update,
)
from typed_coinbase.app.advanced_trade.streams.user.orders import UserOrdersMessage

from tribulnation.coinbase.core.mixin import Shared
from tribulnation.sdk.market import Book, Trade

TIME = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


class FakeSource:
  """A queue posing as one of Coinbase's WebSocket channels."""

  def __init__(self):
    self.queue: asyncio.Queue[Any] = asyncio.Queue()
    self.unsubscribe_count = 0

  def __aiter__(self):
    return self

  async def __anext__(self) -> Any:
    message = await self.queue.get()
    if message is None:
      raise StopAsyncIteration
    return message

  async def send(self, message: Any) -> None:
    """Push one frame to every consumer."""
    await self.queue.put(message)

  async def unsubscribe(self) -> None:
    """Record the teardown and stop consumers."""
    self.unsubscribe_count += 1
    await self.queue.put(None)


class FakeStreams:
  """The `client.app.advanced_trade.streams` chain, backed by one fake source."""

  def __init__(self, source: FakeSource):
    self.source = source

  def level2(self, product_ids: list[str]) -> Any:
    return self

  def orders(self) -> Any:
    return self

  @property
  def market_data(self) -> Any:
    return self

  @property
  def user(self) -> Any:
    return self

  @property
  def streams(self) -> Any:
    return self

  @property
  def advanced_trade(self) -> Any:
    return self

  @property
  def app(self) -> Any:
    return self

  def __await__(self):
    async def connect() -> FakeSource:
      return self.source

    return connect().__await__()


def fake_client(source: FakeSource) -> Coinbase:
  """A stand-in client whose stream chain resolves to `source`."""
  return cast(Coinbase, FakeStreams(source))


def level2_update(side: Literal['bid', 'offer'], price: str, qty: str) -> Level2Update:
  """Build one price-level change; the ask side reads `offer` on the wire."""
  return {
    'side': side,
    'event_time': TIME,
    'price_level': Decimal(price),
    'new_quantity': Decimal(qty),
  }


def level2(kind: str, *, bids: list[tuple[str, str]], asks: list[tuple[str, str]]):
  """Build one `level2` frame."""
  updates = [level2_update('bid', price, qty) for price, qty in bids]
  updates += [level2_update('offer', price, qty) for price, qty in asks]
  message: Level2Message = {
    'channel': 'l2_data',
    'timestamp': TIME,
    'sequence_num': 0,
    'events': [{'type': cast(Any, kind), 'product_id': 'BTC-USD', 'updates': updates}],
  }
  return message


def user_orders(order_id: str, cumulative: str):
  """Build one `user` frame carrying an order's cumulative filled quantity."""
  message: UserOrdersMessage = {
    'channel': 'user',
    'timestamp': TIME,
    'sequence_num': 0,
    'events': [
      {
        'type': 'update',
        'orders': [
          {
            'client_order_id': 'c-1',
            'order_id': order_id,
            'order_side': 'BUY',
            'order_type': 'LIMIT',
            'product_id': 'BTC-USD',
            'product_type': 'SPOT',
            'status': 'OPEN',
            'time_in_force': 'GOOD_UNTIL_CANCELLED',
            'cumulative_quantity': Decimal(cumulative),
            'avg_price': Decimal('100'),
          }
        ],
        'positions': {
          'perpetual_futures_positions': [],
          'expiring_futures_positions': [],
          'prediction_market_positions': [],
        },
      }
    ],
  }
  return message


async def take(stream: AsyncIterable[Any]) -> Any:
  """Read the next item off a stream, with a deadline."""
  return await asyncio.wait_for(anext(aiter(stream)), timeout=1)


async def test_a_late_book_subscriber_still_gets_a_whole_book() -> None:
  """The second subscriber misses the snapshot frame and every delta before it.

  With the fold downstream of the fan-out it would see only the one delta that
  arrived after it joined -- a book with a single bid and no asks at all.
  """
  source = FakeSource()
  shared = Shared(client=fake_client(source))
  sub = shared.book_subscription('BTC-USD')

  async with sub.subscribe(queue_size=100, overflow='fail') as first:
    await source.send(level2('snapshot', bids=[('100', '1')], asks=[('101', '2')]))
    await take(first)
    async with sub.subscribe(queue_size=100, overflow='fail') as second:
      await source.send(level2('update', bids=[('98', '3')], asks=[]))
      await take(first)
      book: Book = await take(second)
      assert [entry.price for entry in book.bids] == [Decimal('100'), Decimal('98')]
      assert book.best_ask.price == Decimal('101')


async def test_a_repeated_order_frame_does_not_invent_a_trade() -> None:
  """The `user` channel carries cumulative order state, not itemized fills.

  It re-sends a frame whenever anything on the order changes, so emitting a trade per
  frame -- rather than per increase in `cumulative_quantity` -- fabricates fills that
  never happened. Reproducing this live means placing real orders.
  """
  source = FakeSource()
  shared = Shared(client=fake_client(source))

  async with shared.user_trades_sub().subscribe(
    queue_size=100, overflow='fail'
  ) as stream:
    await source.send(user_orders('o-1', '1'))
    _, first = cast(tuple[str, Trade], await take(stream))
    assert first.qty == Decimal('1')

    await source.send(user_orders('o-1', '1'))
    await source.send(user_orders('o-1', '3'))
    _, second = cast(tuple[str, Trade], await take(stream))
    assert second.qty == Decimal('2')
