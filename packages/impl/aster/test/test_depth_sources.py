"""`aster.depth_source` picks the partial-depth or `bookTicker` feed, shared per source."""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from typed_core.util import Stream, StreamManager
from typed_core.validation import validator
from typed_aster.core.transport.ws.streams import SocketStreamClient
from typed_aster.futures.market.depth import Depth as FuturesDepth
from typed_aster.futures.streams.schemas import FuturesBookTickerEvent
from typed_aster.schemas import BookTickerEvent, DepthUpdate
from typed_aster.spot.market.depth import Depth as SpotDepth
from typing_extensions import Any, AsyncIterator, cast

from tribulnation.aster import AsterMarket
from tribulnation.aster.core import DepthSource, Scope
from tribulnation.aster.market.markets import PerpMarket, SpotMarket
from tribulnation.aster.market.streams import depth_source, parse_bbo
from tribulnation.sdk.core import OverflowPolicy, skipped
from tribulnation.sdk.market import Settings

TIME_MS = 1791370594322
TIME = datetime(2026, 10, 7, 10, 56, 34, 322000, tzinfo=timezone.utc)
"""The transaction time `T`."""
EVENT = TIME + timedelta(milliseconds=5)
"""The event time `E`."""
CHANNELS: dict[tuple[Scope, DepthSource], str] = {
  ('perp', 'depth'): 'btcusdt@depth20',
  ('perp', 'fast'): 'btcusdt@depth5@100ms',
  ('perp', 'bbo'): 'btcusdt@bookTicker',
  ('spot', 'depth'): 'btcusdt@depth20@100ms',
  ('spot', 'fast'): 'btcusdt@depth5@100ms',
  ('spot', 'bbo'): 'btcusdt@bookTicker',
}
"""The native stream each exchange and source subscribes to."""


def ticker_wire(**fields: Any) -> dict[str, Any]:
  """A raw `bookTicker` push, as Aster sends it."""
  wire: dict[str, Any] = {
    'e': 'bookTicker',
    'u': 7,
    'E': TIME_MS + 5,
    'T': TIME_MS,
    's': 'BTCUSDT',
    'b': '100',
    'B': '1.5',
    'a': '101',
    'A': '2',
  }
  return wire | fields


def depth_wire(levels: int) -> dict[str, Any]:
  """A raw partial-depth push with `levels` levels per side."""
  return {
    'e': 'depthUpdate',
    'E': TIME_MS + 5,
    'T': TIME_MS,
    's': 'BTCUSDT',
    'U': 1,
    'u': 2,
    'pu': 0,
    'b': [[str(100 - i), '1'] for i in range(levels)],
    'a': [[str(101 + i), '1'] for i in range(levels)],
  }


def message(channel: str) -> Any:
  """A validated push for a channel, shaped as its feed sends it."""
  if channel.endswith('@bookTicker'):
    return validator(FuturesBookTickerEvent).python(ticker_wire())
  levels = 5 if '@depth5' in channel else 20
  return validator(DepthUpdate).python(depth_wire(levels))


def market(venue: AsterMarket, scope: Scope) -> SpotMarket | PerpMarket:
  """A market sharing the venue's owner, without catalogue requests."""
  cls = PerpMarket if scope == 'perp' else SpotMarket
  return cls(shared=venue.shared, symbol='BTCUSDT')


def settings(source: DepthSource) -> Settings:
  """Venue settings selecting `source`."""
  return {'aster': {'depth_source': source}}


def test_parse_perp_bbo():
  """A perpetual `bookTicker` push is a one-level book timed by `E`."""
  book = parse_bbo(validator(FuturesBookTickerEvent).python(ticker_wire()))
  assert [(e.price, e.qty) for e in book.bids] == [(Decimal(100), Decimal('1.5'))]
  assert [(e.price, e.qty) for e in book.asks] == [(Decimal(101), Decimal(2))]
  assert book.time == EVENT


def test_parse_spot_bbo_time_fallback():
  """A spot push without `E` falls back to `T`, and one with neither has no time."""
  row: dict[str, Any] = dict(validator(BookTickerEvent).python(ticker_wire()))
  assert parse_bbo(cast(BookTickerEvent, row)).time == EVENT
  del row['E']
  assert parse_bbo(cast(BookTickerEvent, row)).time == TIME
  del row['T']
  assert parse_bbo(cast(BookTickerEvent, row)).time is None


def test_parse_bbo_empty_side():
  """A side with a zero price or quantity is reported empty."""
  row = validator(BookTickerEvent).python(ticker_wire(a='0', A='0', B='0'))
  book = parse_bbo(row)
  assert book.bids == [] and book.asks == []


def test_depth_source_setting():
  """The default is `'depth'`; other venues' keys are ignored; unknown values raise."""
  assert depth_source({}) == 'depth'
  assert depth_source({'hyperliquid': {'depth_source': 'bbo'}}) == 'depth'
  assert depth_source(settings('bbo')) == 'bbo'
  with pytest.raises(ValueError, match='depth_source'):
    depth_source(cast(Settings, {'aster': {'depth_source': 'l2'}}))


@pytest.mark.parametrize('scope', ['spot', 'perp'])
async def test_invalid_stream_arguments(scope: Scope):
  """An unknown source or out-of-range `levels` raises before subscribing."""
  async with AsterMarket.new(public=True, mainnet=False) as venue:
    m = market(venue, scope)
    with pytest.raises(ValueError):
      m.depth_stream(settings=cast(Settings, {'aster': {'depth_source': 'l2'}}))
    with pytest.raises(ValueError):
      m.depth_stream(levels=21, settings=settings('bbo'))


class Feeds:
  """Fake combined-stream subscriptions, recording each native channel's lifetime."""

  def __init__(self, *, skips_per_push: int = 0):
    self.subscribed: list[str] = []
    self.unsubscribed: list[str] = []
    self.keep_latest: list[tuple[str, bool]] = []
    """Each subscription's channel and its typed `keep_latest` flag, in order."""
    self.skips_per_push = skips_per_push
    """How many frames each push pretends were skipped upstream before it."""
    self.skipped = 0
    """What every fake subscription reports as skipped upstream so far."""

  def install(self, monkeypatch: pytest.MonkeyPatch):
    """Route every combined-stream subscription to this fake."""

    def subscribe(
      client: object, channel: str, *, keep_latest: bool = False, **_: Any
    ) -> StreamManager:
      """Replace `SocketStreamClient.subscribe`."""
      return self.subscribe(channel, keep_latest=keep_latest)

    monkeypatch.setattr(SocketStreamClient, 'subscribe', subscribe)

  def subscribe(self, channel: str, *, keep_latest: bool = False) -> StreamManager:
    """Push one message for the channel, then idle until unsubscribed."""

    async def connect() -> Stream:
      """Open the fake subscription."""
      self.subscribed.append(channel)
      self.keep_latest.append((channel, keep_latest))

      async def rows() -> AsyncIterator[Any]:
        """Yield one push, then wait."""
        self.skipped += self.skips_per_push
        yield message(channel)
        await asyncio.Event().wait()

      async def unsubscribe():
        """Record the release."""
        self.unsubscribed.append(channel)

      return Stream(
        reply=None,
        stream=rows(),
        unsubscribe=unsubscribe,
        skipped_count=lambda: self.skipped,
      )

    return StreamManager(connect=connect)


@pytest.mark.parametrize('scope', ['spot', 'perp'])
@pytest.mark.parametrize('source', ['depth', 'fast', 'bbo'])
async def test_source_channel(
  scope: Scope, source: DepthSource, monkeypatch: pytest.MonkeyPatch
):
  """Each source subscribes to its own native stream and parses its pushes."""
  feeds = Feeds()
  feeds.install(monkeypatch)
  async with AsterMarket.new(public=True, mainnet=False) as venue:
    async with market(venue, scope).depth_stream(settings=settings(source)) as books:
      book = await anext(aiter(books))
  assert feeds.subscribed == feeds.unsubscribed == [CHANNELS[scope, source]]
  assert len(book.bids) == {'depth': 20, 'fast': 5, 'bbo': 1}[source]
  assert book.time == EVENT


@pytest.mark.parametrize('scope', ['spot', 'perp'])
async def test_parallel_sources_share_per_source(
  scope: Scope, monkeypatch: pytest.MonkeyPatch
):
  """Sources of one symbol run side by side; subscribers of one source share it."""
  feeds = Feeds()
  feeds.install(monkeypatch)
  async with AsterMarket.new(public=True, mainnet=False) as venue:
    m = market(venue, scope)
    async with (
      m.depth_stream() as deep,
      m.depth_stream(settings=settings('bbo')) as top,
      m.depth_stream(levels=1, settings=settings('bbo')) as top_again,
    ):
      books = await asyncio.gather(*(anext(aiter(s)) for s in (deep, top, top_again)))
    assert sorted(feeds.subscribed) == sorted(
      [CHANNELS[scope, 'depth'], CHANNELS[scope, 'bbo']]
    )
    assert sorted(feeds.unsubscribed) == sorted(feeds.subscribed)
  assert [len(b.bids) for b in books] == [20, 1, 1]


@pytest.mark.parametrize('scope', ['spot', 'perp'])
@pytest.mark.parametrize(
  ('source', 'levels', 'limit', 'kept'),
  [
    ('depth', None, 1000, 20),
    ('depth', 3, 5, 3),
    ('fast', None, 5, 5),
    ('fast', 3, 5, 3),
    ('fast', 50, 5, 5),
    ('bbo', None, 5, 1),
  ],
)
async def test_rest_depth_shape(
  scope: Scope,
  source: DepthSource,
  levels: int | None,
  limit: int,
  kept: int,
  monkeypatch: pytest.MonkeyPatch,
):
  """REST `depth` trims `'fast'` and `'bbo'` to the stream's shape; `'depth'` does not."""
  requested: list[int] = []
  wire = depth_wire(20)
  payload: dict[str, Any] = {
    'lastUpdateId': 1,
    'E': wire['E'],
    'T': wire['T'],
    'symbol': 'BTCUSDT',
    'bids': [(Decimal(p), Decimal(q)) for p, q in wire['b']],
    'asks': [(Decimal(p), Decimal(q)) for p, q in wire['a']],
  }

  async def depth(self: object, symbol: str, *, limit: int, **_: Any):
    """Record the requested limit and return 20 levels."""
    requested.append(limit)
    return payload

  monkeypatch.setattr(SpotDepth if scope == 'spot' else FuturesDepth, 'depth', depth)
  async with AsterMarket.new(public=True, mainnet=False) as venue:
    book = await market(venue, scope).depth(levels=levels, settings=settings(source))
  assert requested == [limit]
  assert len(book.bids) == len(book.asks) == kept
  assert book.time == EVENT


@pytest.mark.parametrize('scope', ['spot', 'perp'])
@pytest.mark.parametrize('source', ['depth', 'fast', 'bbo'])
@pytest.mark.parametrize(
  ('queue_size', 'overflow', 'keep_latest'),
  [(1, 'latest', True), (5, 'latest', False), (100, 'fail', False)],
)
async def test_keep_latest_only_for_latest_only_subscribers(
  scope: Scope,
  source: DepthSource,
  queue_size: int,
  overflow: OverflowPolicy,
  keep_latest: bool,
  monkeypatch: pytest.MonkeyPatch,
):
  """Snapshot feeds conflate upstream only when the subscriber wants the newest book."""
  feeds = Feeds()
  feeds.install(monkeypatch)
  async with AsterMarket.new(public=True, mainnet=False) as venue:
    stream = market(venue, scope).depth_stream(
      queue_size=queue_size, overflow=overflow, settings=settings(source)
    )
    async with stream as books:
      await anext(aiter(books))
  assert feeds.keep_latest == [(CHANNELS[scope, source], keep_latest)]


@pytest.mark.parametrize('scope', ['spot', 'perp'])
async def test_capturing_subscriber_reopens_a_conflated_feed(
  scope: Scope, monkeypatch: pytest.MonkeyPatch
):
  """A subscriber wanting every book reopens the shared feed without `keep_latest`."""
  feeds = Feeds()
  feeds.install(monkeypatch)
  channel = CHANNELS[scope, 'depth']
  async with AsterMarket.new(public=True, mainnet=False) as venue:
    m = market(venue, scope)
    async with m.depth_stream() as newest:
      await anext(aiter(newest))
      async with m.depth_stream(queue_size=100, overflow='fail') as every:
        await anext(aiter(every))
        await anext(aiter(newest))
  assert feeds.keep_latest == [(channel, True), (channel, False)]
  assert feeds.unsubscribed == [channel, channel]


@pytest.mark.parametrize('scope', ['spot', 'perp'])
async def test_skipped_reports_upstream_skips(
  scope: Scope, monkeypatch: pytest.MonkeyPatch
):
  """The yielded stream counts the snapshots its conflated feed skipped."""
  feeds = Feeds(skips_per_push=3)
  feeds.install(monkeypatch)
  async with AsterMarket.new(public=True, mainnet=False) as venue:
    async with market(venue, scope).depth_stream() as books:
      assert skipped(books) == 0
      await anext(aiter(books))
      assert skipped(books) == 3
