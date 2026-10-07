"""Hyperliquid depth: `l2Book`/`bbo` parsing, `depth_source` selection and fan-out."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from typed_core.validation import validator
from typed_hyperliquid import Hyperliquid
from typed_hyperliquid.core.ws import SocketClient
from typed_hyperliquid.info.l2_book import L2Book
from typed_hyperliquid.streams import Streams
from typed_hyperliquid.streams.l2_book import L2BookUpdate
from typing_extensions import Any, AsyncIterator, cast

from tribulnation.sdk.market import Settings
from tribulnation.hyperliquid.core import DepthSource
from tribulnation.hyperliquid.market.impl.depth import (
  depth,
  depth_stream,
  parse_bbo,
  parse_book,
)
from tribulnation.hyperliquid.market.impl.mixin import (
  BboUpdate,
  PerpMarketMixin,
  Shared,
  closing_fast_streams,
)

TIME_MS = 1791370594322
TIME = datetime(2026, 10, 7, 10, 56, 34, 322000, tzinfo=timezone.utc)


def wire(levels: int = 2) -> dict[str, Any]:
  """A raw `l2Book` payload with `levels` levels per side, as Hyperliquid sends it."""
  return {
    'coin': 'BTC',
    'time': TIME_MS,
    'levels': [
      [{'px': str(100 - i), 'sz': str(i + 1), 'n': 1} for i in range(levels)],
      [{'px': str(101 + i), 'sz': str(i + 1), 'n': 1} for i in range(levels)],
    ],
  }


def bbo_wire(*, bid: bool = True, ask: bool = True) -> dict[str, Any]:
  """A raw `bbo` payload; a missing side is `null`, as Hyperliquid sends it."""
  return {
    'coin': 'BTC',
    'time': TIME_MS,
    'bbo': [
      {'px': '100', 'sz': '1.5', 'n': 3} if bid else None,
      {'px': '101', 'sz': '2.5', 'n': 4} if ask else None,
    ],
  }


def settings(source: DepthSource) -> Settings:
  """Venue-keyed settings selecting `source`, beside another venue's key."""
  return {'hyperliquid': {'depth_source': source}, 'dydx': {}}


@pytest.mark.parametrize('Type', [L2Book, L2BookUpdate])
def test_parse_validated_time(Type: type[L2Book] | type[L2BookUpdate]):
  """Validated REST and WS payloads decode `time` to the aware UTC snapshot time."""
  raw: L2Book | L2BookUpdate = validator(Type).python(wire())
  book = parse_book(raw)
  assert book.time == TIME
  assert book.time is not None and book.time.utcoffset() is not None
  assert book.best_bid.price == Decimal('100')
  assert book.best_ask.price == Decimal('101')


def test_parse_unvalidated_time():
  """An unvalidated payload's millisecond epoch converts to the same datetime."""
  book = parse_book(cast(L2Book, wire()))
  assert book.time == TIME
  assert book.time is not None and book.time.tzinfo is not None


def test_parse_levels_keeps_time():
  """Trimming to the top of book keeps the snapshot time."""
  book = parse_book(cast(L2Book, wire()), levels=1)
  assert [e.price for e in book.bids] == [Decimal('100')]
  assert [e.price for e in book.asks] == [Decimal('101')]
  assert book.time == TIME


def test_parse_bbo():
  """A `bbo` push becomes a one-level book with sizes and the exchange time."""
  book = parse_bbo(validator(BboUpdate).python(bbo_wire()))
  assert [(e.price, e.qty) for e in book.bids] == [(Decimal('100'), Decimal('1.5'))]
  assert [(e.price, e.qty) for e in book.asks] == [(Decimal('101'), Decimal('2.5'))]
  assert book.time == TIME


@pytest.mark.parametrize('bid,ask', [(False, True), (True, False), (False, False)])
def test_parse_bbo_missing_side(bid: bool, ask: bool):
  """A `null` side validates and becomes an empty side."""
  book = parse_bbo(validator(BboUpdate).python(bbo_wire(bid=bid, ask=ask)))
  assert len(book.bids) == bid
  assert len(book.asks) == ask
  assert book.time == TIME


def test_parse_bbo_levels():
  """`levels` trims a `bbo` book like any other; `0` empties it."""
  raw = validator(BboUpdate).python(bbo_wire())
  assert len(parse_bbo(raw, levels=5).bids) == 1
  assert parse_bbo(raw, levels=0).bids == []


def rest_market(levels: int) -> PerpMarketMixin:
  """A market whose REST `l2Book` answers with `levels` levels per side."""

  async def l2_book(*, coin: str):
    """Return the fixture payload for the requested coin."""
    assert coin == 'BTC'
    return validator(L2Book).python(wire(levels))

  market = SimpleNamespace(
    client=SimpleNamespace(info=SimpleNamespace(l2_book=l2_book)), asset_name='BTC'
  )
  return cast(PerpMarketMixin, market)


async def test_depth_populates_time():
  """The REST `depth` snapshot carries the exchange time."""
  book = await depth(rest_market(2))
  assert book.time == TIME


@pytest.mark.parametrize(
  'source,levels,expected',
  [
    ('l2', None, 20),
    ('l2', 3, 3),
    ('fast', None, 5),
    ('fast', 3, 3),
    ('fast', 10, 5),
    ('bbo', None, 1),
    ('bbo', 10, 1),
  ],
)
async def test_depth_rest_shape(source: DepthSource, levels: int | None, expected: int):
  """REST reads the 20-level snapshot, trimmed to the source's shape and `levels`."""
  book = await depth(rest_market(20), levels=levels, settings=settings(source))
  assert len(book.bids) == len(book.asks) == expected
  assert book.best_bid.price == Decimal('100')
  assert book.time == TIME


def l2_messages(levels: int) -> list[dict[str, Any]]:
  """Two `l2Book` pushes with `levels` levels per side, one second apart."""
  return [wire(levels), wire(levels) | {'time': TIME_MS + 1000}]


def bbo_messages() -> list[dict[str, Any]]:
  """Two `bbo` pushes one second apart, the second without an ask."""
  return [bbo_wire(), bbo_wire(ask=False) | {'time': TIME_MS + 1000}]


MESSAGES = {'l2': l2_messages(20), 'fast': l2_messages(5), 'bbo': bbo_messages()}


@pytest.mark.parametrize(
  'source,levels,expected',
  [
    ('l2', None, [20, 20]),
    ('l2', 3, [3, 3]),
    ('fast', None, [5, 5]),
    ('fast', 2, [2, 2]),
    ('bbo', None, [1, 1]),
    ('bbo', 5, [1, 1]),
  ],
)
async def test_depth_stream_sources(
  source: DepthSource, levels: int | None, expected: list[int]
):
  """Each source parses into books with the exchange time; `levels` only trims."""
  seen: list[tuple[str, DepthSource]] = []

  @asynccontextmanager
  async def subscribe_depth(coin: str, source: DepthSource, /, **_: Any):
    """Push the source's fixture messages."""
    seen.append((coin, source))

    async def messages():
      """Yield the fixture messages."""
      for msg in MESSAGES[source]:
        yield msg

    yield messages()

  market = SimpleNamespace(subscribe_depth=subscribe_depth, asset_name='BTC')
  async with depth_stream(
    cast(PerpMarketMixin, market), levels=levels, settings=settings(source)
  ) as stream:
    books = [book async for book in stream]
  assert seen == [('BTC', source)]
  assert [len(b.bids) for b in books] == expected
  assert [b.time for b in books] == [TIME, TIME + timedelta(seconds=1)]
  if source == 'bbo':
    assert [len(b.asks) for b in books] == [1, 0]


async def test_depth_stream_defaults_to_l2():
  """Without a `hyperliquid.depth_source` setting the stream reads `'l2'`."""
  seen: list[DepthSource] = []

  @asynccontextmanager
  async def subscribe_depth(_coin: str, source: DepthSource, /, **_: Any):
    """Record the source and push nothing."""
    seen.append(source)

    async def messages() -> AsyncIterator[dict[str, Any]]:
      """Yield nothing."""
      for msg in list[dict[str, Any]]():
        yield msg

    yield messages()

  market = cast(
    PerpMarketMixin, SimpleNamespace(subscribe_depth=subscribe_depth, asset_name='BTC')
  )
  async with depth_stream(market) as stream:
    [book async for book in stream]
  async with depth_stream(market, settings={'dydx': {}}) as stream:
    [book async for book in stream]
  assert seen == ['l2', 'l2']


@dataclass
class FakeStream:
  """A typed-client stream: async-iterable, with an `unsubscribe` coroutine."""

  messages: list[dict[str, Any]]
  unsubscribed: int = 0

  def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
    """Yield the messages."""

    async def gen():
      """Yield the messages."""
      for msg in self.messages:
        yield msg

    return gen()

  async def unsubscribe(self):
    """Count unsubscriptions."""
    self.unsubscribed += 1


@dataclass
class FakeStreams:
  """Record every `l2_book`/`bbo` subscribe made on one connection."""

  calls: list[tuple[str, str, dict[str, Any]]] = field(
    default_factory=list[tuple[str, str, dict[str, Any]]]
  )
  bbo_messages: list[dict[str, Any]] = field(default_factory=bbo_messages)

  async def l2_book(self, coin: str, **kwargs: Any) -> FakeStream:
    """Subscribe to `l2Book`."""
    self.calls.append(('l2Book', coin, kwargs))
    return FakeStream(l2_messages(5 if kwargs.get('fast') else 20))

  async def bbo(self, coin: str, **kwargs: Any) -> FakeStream:
    """Subscribe to `bbo`."""
    self.calls.append(('bbo', coin, kwargs))
    return FakeStream(self.bbo_messages)


def fake_shared() -> tuple[Shared, FakeStreams, FakeStreams]:
  """A `Shared` whose main and dedicated `'fast'` connections are recorded."""
  main, fast = FakeStreams(), FakeStreams()
  client = SimpleNamespace(streams=main, validate=True)
  shared = Shared(client=cast(Hyperliquid, client))
  shared.fast_streams = cast(Streams, fast)
  return shared, main, fast


async def first(shared: Shared, coin: str, source: DepthSource) -> Any:
  """Subscribe once and read the first message."""
  sub = shared.depth_subscription(coin, source)
  async with sub.subscribe(queue_size=10) as stream:
    return await anext(aiter(stream))


def test_subscriptions_keyed_by_coin_and_source():
  """One upstream per `(coin, source)`: the same key shares, other sources don't."""
  shared, _, _ = fake_shared()
  sub = shared.depth_subscription('BTC', 'l2')
  assert shared.depth_subscription('BTC', 'l2') is sub
  keys: list[tuple[str, DepthSource]] = [
    ('BTC', 'l2'),
    ('BTC', 'fast'),
    ('BTC', 'bbo'),
    ('ETH', 'l2'),
  ]
  assert len({id(shared.depth_subscription(*key)) for key in keys}) == 4
  assert set(shared.depth_subscriptions) == set(keys)


async def test_consumers_share_one_upstream():
  """Two consumers of one `(coin, source)` share a single upstream subscribe."""
  shared, main, _ = fake_shared()
  sub = shared.depth_subscription('BTC', 'bbo')
  async with (
    sub.subscribe(queue_size=10) as a,
    sub.subscribe(queue_size=10) as b,
  ):
    assert await anext(aiter(a)) == await anext(aiter(b))
  assert [call[:2] for call in main.calls] == [('bbo', 'BTC')]


async def test_fast_uses_dedicated_connection():
  """`'fast'` subscribes on the dedicated connection; `'l2'`/`'bbo'` on the main one."""
  shared, main, fast = fake_shared()
  l2 = await first(shared, 'BTC', 'l2')
  fast_msg = await first(shared, 'BTC', 'fast')
  bbo = await first(shared, 'BTC', 'bbo')

  assert main.calls == [
    ('l2Book', 'BTC', {}),
    ('bbo', 'BTC', {'validate': False}),
  ]
  assert fast.calls == [('l2Book', 'BTC', {'fast': True})]
  assert len(l2['levels'][0]) == 20
  assert len(fast_msg['levels'][0]) == 5
  assert 'bbo' in bbo


async def test_bbo_validation_accepts_missing_side():
  """The `bbo` upstream validates its pushes with `null` sides allowed."""
  shared, main, _ = fake_shared()
  main.bbo_messages = [bbo_wire(bid=False)]
  msg = await first(shared, 'BTC', 'bbo')
  assert msg['bbo'][0] is None
  assert msg['bbo'][1]['px'] == Decimal('101')


def test_fast_connection_copies_main_socket():
  """The dedicated connection is a separate socket to the same URL, built once."""
  main_socket = SocketClient(url='wss://example.invalid/ws')
  client = SimpleNamespace(streams_client=main_socket, validate=False)
  shared = Shared(client=cast(Hyperliquid, client))

  streams = shared.fast_streams_client()
  assert shared.fast_streams_client() is streams
  socket = cast(SocketClient, streams.client)
  assert socket is not main_socket
  assert socket.url == main_socket.url
  assert socket.ping_interval == main_socket.ping_interval
  assert streams.validate is False


async def test_fast_connection_closed_at_exit():
  """Exiting closes the dedicated connection once and forgets it."""
  closed: list[tuple[object, ...]] = []

  class Socket:
    """Record `__aexit__`."""

    async def __aexit__(self, *args: object):
      """Record the close."""
      closed.append(args)

  shared = Shared(client=cast(Hyperliquid, SimpleNamespace()))
  async with closing_fast_streams(shared):
    shared.fast_streams = cast(Streams, SimpleNamespace(client=Socket()))
  assert closed == [(None, None, None)]
  assert shared.fast_streams is None

  async with closing_fast_streams(shared):
    pass
  assert len(closed) == 1
