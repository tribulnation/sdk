from typing_extensions import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
import asyncio
from contextlib import asynccontextmanager, suppress

from tribulnation.sdk.market import Book
from tribulnation.sdk.core import NetworkError, OverflowPolicy
from tribulnation.mexc.core.exc import wrap_exceptions
from mexc import MEXC
from mexc.spot.market.depth import OrderBook
from mexc.spot.streams.core.proto import PublicAggreDepthsV3Api

from .mixin import MarketMixin


@wrap_exceptions
async def depth(self: MarketMixin, *, levels: int | None = None) -> Book:
  r = await self.client.spot.market.depth(symbol=self.instrument, validate=self.shared.validate, limit=levels)
  return Book(
    asks=[Book.Entry(price=Decimal(p), qty=Decimal(q)) for p, q in r['asks']],
    bids=[Book.Entry(price=Decimal(p), qty=Decimal(q)) for p, q in r['bids']],
  )


@dataclass(kw_only=True)
class DepthUpdate:
  from_version: int
  to_version: int
  book: Book

def parse_snapshot(reply: OrderBook) -> tuple[int, Book]:
  return int(reply['lastUpdateId']), Book(
    asks=[Book.Entry(price=Decimal(p), qty=Decimal(q)) for p, q in reply['asks']],
    bids=[Book.Entry(price=Decimal(p), qty=Decimal(q)) for p, q in reply['bids']],
  )

def parse_update(msg: PublicAggreDepthsV3Api) -> DepthUpdate:
  return DepthUpdate(
    from_version=int(msg.from_version),
    to_version=int(msg.to_version),
    book=Book(
      asks=[Book.Entry(price=Decimal(a.price), qty=Decimal(a.quantity)) for a in msg.asks],
      bids=[Book.Entry(price=Decimal(b.price), qty=Decimal(b.quantity)) for b in msg.bids],
    ),
  )

def drain_updates(queue: asyncio.Queue[DepthUpdate], cache: list[DepthUpdate]) -> None:
  while not queue.empty():
    cache.append(queue.get_nowait())

async def receive_update(
  queue: asyncio.Queue[DepthUpdate],
  collector: asyncio.Task[None],
) -> DepthUpdate:
  if not queue.empty():
    return queue.get_nowait()

  pending_update = asyncio.create_task(queue.get())
  done, _ = await asyncio.wait(
    {pending_update, collector},
    return_when=asyncio.FIRST_COMPLETED,
  )
  if pending_update in done:
    return pending_update.result()

  pending_update.cancel()
  with suppress(asyncio.CancelledError):
    await pending_update
  exc = collector.exception()
  if exc is not None:
    raise exc
  raise RuntimeError('Depth update stream ended')


async def synchronized_book(
  client: MEXC,
  symbol: str,
  queue: asyncio.Queue[DepthUpdate],
  collector: asyncio.Task[None],
  levels: int | None = None,
) -> tuple[int, Book]:
  cache = [await receive_update(queue, collector)]

  while True:
    first = cache[0]
    version, book = parse_snapshot(
      await client.spot.market.depth(symbol=symbol, limit=levels)
    )
    drain_updates(queue, cache)

    if version < first.from_version:
      continue

    cache = [update for update in cache if update.to_version > version]
    if cache and cache[0].from_version > version + 1:
      cache = [await receive_update(queue, collector)]
      continue

    for update in cache:
      if update.to_version <= version:
        continue
      if update.from_version > version + 1:
        break
      book.update(update.book)
      version = update.to_version
    else:
      return version, book

    cache = [await receive_update(queue, collector)]


@wrap_exceptions
async def reconstruct_books(
  client: MEXC,
  symbol: str,
  updates: AsyncIterable[PublicAggreDepthsV3Api],
  *,
  levels: int | None = None,
) -> AsyncIterator[Book]:
  """Reconstruct a live order book from MEXC's snapshot + incremental diff feed.

  Runs once per shared subscription (not per consumer): the resulting full-book
  snapshots are fanned out by the `Subscription`, so each consumer's bounded
  inbox holds whole books rather than a growing backlog of raw diffs.
  """
  queue: asyncio.Queue[DepthUpdate] = asyncio.Queue(maxsize=100)

  async def collect() -> None:
    async for msg in updates:
      if queue.full():
        raise NetworkError('Depth reconstruction fell behind')
      queue.put_nowait(parse_update(msg))

  collector = asyncio.create_task(collect())
  try:
    while True:
      version, book = await synchronized_book(client, symbol, queue, collector, levels=levels)
      yield book.copy()

      while True:
        update = await receive_update(queue, collector)
        if update.to_version <= version:
          continue
        if update.from_version != version + 1:
          break
        book.update(update.book)
        version = update.to_version
        yield book.copy()
  finally:
    collector.cancel()
    with suppress(asyncio.CancelledError):
      await collector


@asynccontextmanager
@wrap_exceptions
async def depth_stream(
  self: MarketMixin,
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
):
  # `levels` is accepted for API compatibility but does not size the shared
  # streaming book (mirrors dYdX); use `depth(levels=...)` for a sized snapshot.
  async with self.subscribe_depth(queue_size=queue_size, overflow=overflow) as stream:
    yield stream
