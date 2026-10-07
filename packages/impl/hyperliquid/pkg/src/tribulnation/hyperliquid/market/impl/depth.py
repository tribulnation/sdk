"""Hyperliquid order books: REST `l2Book` snapshots and the `depth_source` WS feeds."""

from typing_extensions import AsyncIterable, Mapping
from contextlib import asynccontextmanager
from decimal import Decimal

from tribulnation.sdk.market import Book, Settings
from tribulnation.sdk.core import OverflowPolicy
from tribulnation.sdk.util import epoch_time

from typed_hyperliquid.core import timestamp_millis
from typed_hyperliquid.info.l2_book import L2Book
from typed_hyperliquid.streams.l2_book import L2BookUpdate

from tribulnation.hyperliquid.core import DepthSource, wrap_exceptions
from .mixin import BboUpdate, DepthMessage, SpotMarketMixin, PerpMarketMixin

Mixin = SpotMarketMixin | PerpMarketMixin

SOURCE_LEVELS: Mapping[DepthSource, int] = {'l2': 20, 'fast': 5, 'bbo': 1}
"""Levels per side each source delivers; REST `depth` trims to the same shape."""


def depth_source(settings: Settings) -> DepthSource:
  """The `hyperliquid.depth_source` setting, defaulting to `'l2'`.

  Args:
    settings: Venue-keyed settings; only the `hyperliquid` key is read.
  """
  return settings.get('hyperliquid', {}).get('depth_source', 'l2')


def cap_levels(source: DepthSource, levels: int | None) -> int:
  """The levels per side to keep: the caller's `levels`, capped at the source's shape.

  Args:
    source: The selected depth source.
    levels: The caller's requested cap, if any.
  """
  limit = SOURCE_LEVELS[source]
  return limit if levels is None else min(levels, limit)


def parse_book(raw: L2Book | L2BookUpdate, *, levels: int | None = None) -> Book:
  """Convert an `l2Book` REST snapshot or WS message, keeping its exchange time.

  Args:
    raw: The `l2Book` payload.
    levels: Keep at most this many levels per side (venue order is best first).
  """
  raw_bids, raw_asks = raw['levels']
  return Book(
    bids=[
      Book.Entry(price=Decimal(b['px']), qty=Decimal(b['sz']))
      for b in raw_bids[:levels]
    ],
    asks=[
      Book.Entry(price=Decimal(a['px']), qty=Decimal(a['sz']))
      for a in raw_asks[:levels]
    ],
    time=epoch_time(raw['time'], timestamp_millis),
  )


def parse_bbo(raw: BboUpdate, *, levels: int | None = None) -> Book:
  """Convert a `bbo` message into a top-of-book `Book`, keeping its exchange time.

  An empty side (`null` on the wire) becomes an empty list.

  Args:
    raw: The `bbo` payload.
    levels: `0` empties both sides; any other value keeps the single level.
  """
  bid, ask = raw['bbo']
  keep = levels is None or levels > 0
  bids = [bid] if bid is not None and keep else []
  asks = [ask] if ask is not None and keep else []
  return Book(
    bids=[Book.Entry(price=Decimal(b['px']), qty=Decimal(b['sz'])) for b in bids],
    asks=[Book.Entry(price=Decimal(a['px']), qty=Decimal(a['sz'])) for a in asks],
    time=epoch_time(raw['time'], timestamp_millis),
  )


def parse_depth(raw: DepthMessage, *, levels: int | None = None) -> Book:
  """Convert any depth push, `l2Book` or `bbo`, into a `Book`.

  Args:
    raw: The pushed payload.
    levels: Keep at most this many levels per side.
  """
  if 'bbo' in raw:
    return parse_bbo(raw, levels=levels)
  return parse_book(raw, levels=levels)


@wrap_exceptions
async def depth(
  self: Mixin, *, levels: int | None = None, settings: Settings = {}
) -> Book:
  """Fetch the REST `l2Book` snapshot, trimmed to the selected source's shape.

  REST has no faster endpoint: every source reads the same 20-level snapshot, cut to
  5 levels per side for `'fast'` and 1 for `'bbo'`, and to `levels` if lower.

  Args:
    levels: Keep at most this many levels per side.
    settings: Venue settings; `hyperliquid.depth_source` selects the shape.
  """
  source = depth_source(settings)
  raw = await self.client.info.l2_book(coin=self.asset_name)
  return parse_book(raw, levels=cap_levels(source, levels))


@asynccontextmanager
async def depth_stream(
  self: Mixin,
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
  settings: Settings = {},
):
  """Stream books from the `hyperliquid.depth_source` feed, `'l2'` by default.

  Consumers of one `(coin, source)` share a single upstream subscription. Each source
  is a different feed with its own cadence and depth (see `Settings.depth_source`), so
  books from different sources need not agree tick-for-tick: `'bbo'` usually leads
  the best level of `'l2'` by up to seconds.

  Args:
    levels: Keep at most this many levels per side; it never selects the source.
    queue_size: Books buffered for this subscriber.
    overflow: What to do when the buffer is full.
    settings: Venue settings; `hyperliquid.depth_source` selects the feed.
  """
  source = depth_source(settings)
  async with self.subscribe_depth(
    self.asset_name, source, queue_size=queue_size, overflow=overflow
  ) as messages:

    async def gen() -> AsyncIterable[Book]:
      """Parse each push; `l2Book` and `bbo` both send a full snapshot per message."""
      async for raw in messages:
        yield parse_depth(raw, levels=levels)

    yield gen()
