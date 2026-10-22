"""REST and RFQ depth, and the book maintained from stream snapshots and deltas."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from typing_extensions import Any

import pytest
from typed_extended import Extended

from tribulnation.extended.core import Shared
from tribulnation.extended.market import books
from tribulnation.sdk.core import MissingData, NetworkError
from tribulnation.sdk.market import Book

T0 = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)


@dataclass
class Stream:
  """A stream that pushes fixed frames, then ends."""

  frames: list[dict[str, Any]]
  unsubscribed: bool = False

  def __aiter__(self):
    """Iterate the frames."""
    return self.push()

  async def push(self):
    """Each frame in turn."""
    for frame in self.frames:
      yield frame

  async def unsubscribe(self):
    """Remember the unsubscription."""
    self.unsubscribed = True


@dataclass
class Manager:
  """What a typed stream method returns: awaitable, or an async context manager."""

  stream: Stream
  opened: list[str] = field(default_factory=list[str])

  def __await__(self):
    """Connect."""
    return self.connect().__await__()

  async def connect(self) -> Stream:
    """The fixture stream."""
    return self.stream

  async def __aenter__(self) -> Stream:
    """Connect for a scoped read."""
    return self.stream

  async def __aexit__(self, *args: Any):
    """Unsubscribe on exit."""
    await self.stream.unsubscribe()


def level(p: str, q: str, c: str | None = None) -> dict[str, Any]:
  """A stream level; `c` is the absolute size a delta carries."""
  out: dict[str, Any] = {'p': Decimal(p), 'q': Decimal(q)}
  if c is not None:
    out['c'] = Decimal(c)
  return out


def frame(
  kind: str, seq: int, bids: list[dict[str, Any]], asks: list[dict[str, Any]]
) -> dict[str, Any]:
  """An `orderbooks` frame."""
  return {
    'type': kind,
    'data': {'m': 'BTC-USD', 'b': bids, 'a': asks},
    'ts': T0 + timedelta(seconds=seq),
    'seq': seq,
  }


def snapshot(seq: int, bid: str, ask: str) -> dict[str, Any]:
  """A one-level snapshot."""
  return frame('SNAPSHOT', seq, [level(bid, '1')], [level(ask, '2')])


@pytest.fixture
async def shared():
  """A shared owner with a book market and an RFQ market cached."""
  async with Extended.new(public=True) as client:
    out = Shared(client=client)
    out.markets.update(
      {
        'BTC-USD': {'name': 'BTC-USD', 'type': 'PERPETUAL', 'isRfq': False},  # type: ignore[typeddict-item]
        'OP-USD': {'name': 'OP-USD', 'type': 'PERPETUAL', 'isRfq': True},  # type: ignore[typeddict-item]
      }
    )
    yield out


async def test_rest_depth_and_missing_book(shared: Shared):
  """The REST book has no time; a market the venue has no book for raises."""
  answers: list[Any] = [
    {
      'market': 'BTC-USD',
      'bid': [{'price': Decimal('100'), 'qty': Decimal('1')}],
      'ask': [{'price': Decimal('101'), 'qty': Decimal('2')}],
    },
    None,
  ]

  async def orderbook(market: str) -> Any:
    """The next fixture answer."""
    return answers.pop(0)

  shared.client.info.orderbook = orderbook  # type: ignore[method-assign]
  book = await books.depth(shared, 'BTC-USD')
  assert (book.best_bid.price, book.best_ask.qty, book.time) == (
    Decimal('100'),
    Decimal('2'),
    None,
  )
  with pytest.raises(MissingData) as missing:
    await books.depth(shared, 'BTC-USD')
  assert (missing.value.market_id, missing.value.field) == ('BTC-USD', 'depth')


async def test_rfq_depth_is_the_quotes_snapshot(shared: Shared):
  """An RFQ market's depth is the first quotes snapshot, stamped with its time; the
  REST book is not read."""
  quotes = Stream([frame('DELTA', 1, [], []), snapshot(2, '0.12', '0.13')])
  shared.client.streams.rfq_orderbooks = lambda market, **kw: Manager(quotes)  # type: ignore[method-assign]
  book = await books.depth(shared, 'OP-USD', levels=1)
  assert (book.best_bid.price, book.best_ask.price, book.time) == (
    Decimal('0.12'),
    Decimal('0.13'),
    T0 + timedelta(seconds=2),
  )
  assert quotes.unsubscribed


async def read(shared: Shared, market: str, n: int, **kwargs: Any) -> list[Book]:
  """The first `n` books of the market's depth stream."""
  out: list[Book] = []
  async with books.depth_stream(
    shared, market, queue_size=100, overflow='fail', **kwargs
  ) as stream:
    async for book in stream:
      out.append(book)
      if len(out) == n:
        break
  return out


async def test_deltas_apply_absolute_sizes_and_snapshots_replace(shared: Shared):
  """A delta sets each level to its absolute size `c` (`0` removes it), and a later
  snapshot replaces the book."""
  stream = Stream(
    [
      snapshot(1, '100', '101'),
      frame('DELTA', 2, [level('100', '-1', '0'), level('99', '3', '3')], []),
      snapshot(3, '98', '102'),
    ]
  )
  shared.client.streams.orderbooks = lambda market, **kw: Manager(stream)  # type: ignore[method-assign]
  first, second, third = await read(shared, 'BTC-USD', 3)
  assert [(e.price, e.qty) for e in first.bids] == [(Decimal('100'), Decimal('1'))]
  assert [(e.price, e.qty) for e in second.bids] == [(Decimal('99'), Decimal('3'))]
  assert second.time == T0 + timedelta(seconds=2)
  assert [(e.price, e.qty) for e in third.bids] == [(Decimal('98'), Decimal('1'))]


async def test_a_sequence_gap_fails_the_stream(shared: Shared):
  """A skipped `seq` means a missed delta: the stream fails instead of drifting."""
  stream = Stream([snapshot(1, '100', '101'), frame('DELTA', 3, [], [])])
  shared.client.streams.orderbooks = lambda market, **kw: Manager(stream)  # type: ignore[method-assign]
  with pytest.raises(NetworkError, match='skipped'):
    await read(shared, 'BTC-USD', 3)


async def test_rfq_streams_maintain_the_quotes(shared: Shared):
  """An RFQ market's depth stream reads the quotes stream, trimmed to `levels`."""
  quotes = Stream(
    [
      frame(
        'SNAPSHOT', 1, [level('0.12', '5'), level('0.11', '6')], [level('0.13', '1')]
      )
    ]
  )
  shared.client.streams.rfq_orderbooks = lambda market, **kw: Manager(quotes)  # type: ignore[method-assign]
  (book,) = await read(shared, 'OP-USD', 1, levels=1)
  assert [(e.price, e.qty) for e in book.bids] == [(Decimal('0.12'), Decimal('5'))]


def test_snapshots_are_isolated_without_deep_copies():
  """A frame's book survives later deltas, and a subscriber's entries are its own."""
  book = Book(
    bids=[Book.Entry(Decimal('100'), Decimal('1'))],
    asks=[Book.Entry(Decimal('101'), Decimal('2'))],
  )
  frame_book = books.frozen(book)
  book.update(Book(bids=[Book.Entry(Decimal('100'), Decimal('0'))]))
  assert [e.price for e in frame_book.bids] == [Decimal('100')] and book.bids == []
  mine, theirs = books.detached(frame_book), books.detached(frame_book, 1)
  mine.asks[0].qty = Decimal('9')
  assert theirs.asks[0].qty == frame_book.asks[0].qty == Decimal('2')
