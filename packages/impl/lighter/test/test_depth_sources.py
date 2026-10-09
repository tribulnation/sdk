"""`lighter.depth_source` picks the full `order_book` or the `ticker` best bid/offer."""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from typed_core.validation import validator
from typed_lighter.streams.order_book import OrderBookUpdate
from typed_lighter.streams.ticker import TickerUpdate
from typing_extensions import Any, AsyncIterator, cast

from tribulnation.lighter.core import Shared
from tribulnation.lighter.market import books
from tribulnation.sdk.market import Settings

MARKET = 1
TIME_US = 1791370594322123
TIME = datetime(2026, 10, 7, 10, 56, 34, 322123, tzinfo=timezone.utc)


def ticker_wire(
  *, bid: tuple[str, str] = ('100', '1.5'), ask: tuple[str, str] = ('101', '2')
) -> dict[str, Any]:
  """A raw `ticker` frame, as Lighter sends it."""
  return {
    'type': 'update/ticker',
    'channel': f'ticker:{MARKET}',
    'ticker': {
      's': 'BTC',
      'a': {'price': ask[0], 'size': ask[1]},
      'b': {'price': bid[0], 'size': bid[1]},
      'last_updated_at': TIME_US,
    },
    'nonce': 11,
    'last_updated_at': TIME_US,
    'timestamp': TIME_US // 1000 + 3,
  }


def order_book_wire() -> dict[str, Any]:
  """A raw `order_book` snapshot frame with two levels per side."""
  state: dict[str, Any] = {
    'code': 0,
    'asks': [{'price': '101', 'size': '2'}, {'price': '102', 'size': '1'}],
    'bids': [{'price': '100', 'size': '1'}, {'price': '99', 'size': '1'}],
    'offset': 10,
    'nonce': 10,
    'begin_nonce': 0,
    'last_updated_at': TIME_US,
  }
  return {
    'type': 'subscribed/order_book',
    'channel': f'order_book:{MARKET}',
    'order_book': state,
    'offset': 10,
    'last_updated_at': TIME_US,
    'timestamp': TIME_US // 1000 + 3,
  }


def settings(source: str) -> Settings:
  """Venue settings selecting `source`."""
  return cast(Settings, {'lighter': {'depth_source': source}})


def test_parse_ticker():
  """A `ticker` frame is a one-level book timed by the book change, not the send time."""
  book = books.parse_ticker(validator(TickerUpdate).python(ticker_wire()))
  assert [(e.price, e.qty) for e in book.bids] == [(Decimal(100), Decimal('1.5'))]
  assert [(e.price, e.qty) for e in book.asks] == [(Decimal(101), Decimal(2))]
  assert book.time == TIME


def test_parse_ticker_empty_side():
  """A side with a zero price or size is reported empty."""
  row = validator(TickerUpdate).python(ticker_wire(ask=('0', '0'), bid=('100', '0')))
  book = books.parse_ticker(row)
  assert book.bids == [] and book.asks == []


def test_depth_source_setting():
  """The default is `'order_book'`; other keys are ignored; unknown values raise."""
  assert books.depth_source({}) == 'order_book'
  assert books.depth_source({'lighter': {'reduce_only': True}}) == 'order_book'
  assert books.depth_source({'hyperliquid': {'depth_source': 'bbo'}}) == 'order_book'
  assert books.depth_source(settings('bbo')) == 'bbo'
  with pytest.raises(ValueError, match='depth_source'):
    books.depth_source(settings('ticker'))


class Channels:
  """Fake `order_book` and `ticker` streams, recording each channel's lifetime."""

  def __init__(self):
    self.subscribed: list[str] = []
    self.unsubscribed: list[str] = []

  def stream(self, channel: str, row: Any) -> Any:
    """A stream pushing one frame, then idling until unsubscribed."""
    self.subscribed.append(channel)

    async def rows() -> AsyncIterator[Any]:
      """Yield one frame, then wait."""
      yield row
      await asyncio.Event().wait()

    async def unsubscribe():
      """Record the release."""
      self.unsubscribed.append(channel)

    return Frames(rows(), unsubscribe)

  async def order_book(self, market_id: int) -> Any:
    """Open the fake `order_book` channel."""
    row = validator(OrderBookUpdate).python(order_book_wire())
    return self.stream(f'order_book/{market_id}', row)

  async def ticker(self, market_id: int) -> Any:
    """Open the fake `ticker` channel."""
    return self.stream(
      f'ticker/{market_id}', validator(TickerUpdate).python(ticker_wire())
    )


class Frames:
  """An async-iterable native stream with an `unsubscribe` coroutine."""

  def __init__(self, rows: AsyncIterator[Any], unsubscribe: Any):
    self.rows = rows
    self.unsubscribe = unsubscribe

  def __aiter__(self):
    """Iterate the frames."""
    return self.rows


def fake_shared(channels: Channels) -> Shared:
  """A shared owner whose client streams come from `channels`."""
  streams = SimpleNamespace(order_book=channels.order_book, ticker=channels.ticker)
  return cast(
    Shared, SimpleNamespace(books={}, client=SimpleNamespace(streams=streams))
  )


async def test_parallel_sources_share_per_source():
  """Both sources of one market run side by side; subscribers of one source share it."""
  channels = Channels()
  shared = fake_shared(channels)
  async with (
    books.depth_stream(shared, MARKET) as full,
    books.depth_stream(shared, MARKET, source='bbo') as top,
    books.depth_stream(shared, MARKET, levels=1, source='bbo') as top_again,
  ):
    out = await asyncio.gather(*(anext(aiter(s)) for s in (full, top, top_again)))
  assert sorted(channels.subscribed) == [f'order_book/{MARKET}', f'ticker/{MARKET}']
  assert sorted(channels.unsubscribed) == sorted(channels.subscribed)
  assert [len(b.bids) for b in out] == [2, 1, 1]
  assert [b.time for b in out] == [TIME, TIME, TIME]


async def test_rest_bbo_trims_to_one_level():
  """REST `depth` with `'bbo'` reads the resting-order snapshot, trimmed to one level."""
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
    """Return two resting orders per side."""
    return {
      'code': 200,
      'total_bids': 2,
      'bids': [order | {'price': Decimal(100)}, order | {'price': Decimal(99)}],
      'total_asks': 2,
      'asks': [order | {'price': Decimal(101)}, order | {'price': Decimal(102)}],
    }

  async def call(fn: Any):
    """Run the request directly."""
    return await fn()

  shared = cast(
    Shared,
    SimpleNamespace(
      call=call,
      client=SimpleNamespace(
        api=SimpleNamespace(
          markets=SimpleNamespace(order_book_orders=order_book_orders)
        )
      ),
    ),
  )
  full = await books.depth(shared, MARKET)
  top = await books.depth(shared, MARKET, levels=5, source='bbo')
  assert (len(full.bids), len(full.asks)) == (2, 2)
  assert [e.price for e in top.bids] == [Decimal(100)]
  assert [e.price for e in top.asks] == [Decimal(101)]
