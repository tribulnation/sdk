from typing_extensions import AsyncIterable
from contextlib import asynccontextmanager
from decimal import Decimal

from tribulnation.sdk.market import Book
from tribulnation.sdk.core import OverflowPolicy
from tribulnation.sdk.util import epoch_time

from typed_hyperliquid.core import timestamp_millis
from typed_hyperliquid.info.l2_book import L2Book
from typed_hyperliquid.streams.l2_book import L2BookUpdate

from tribulnation.hyperliquid.core import wrap_exceptions
from .mixin import SpotMarketMixin, PerpMarketMixin

Mixin = SpotMarketMixin | PerpMarketMixin


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


@wrap_exceptions
async def depth(self: Mixin) -> Book:
  return parse_book(await self.client.info.l2_book(coin=self.asset_name))


@asynccontextmanager
async def depth_stream(
  self: Mixin, *, queue_size: int = 1, overflow: OverflowPolicy = 'latest'
):
  async with self.subscribe_l2_book(
    self.asset_name, queue_size=queue_size, overflow=overflow
  ) as l2:

    async def gen() -> AsyncIterable[Book]:
      async for update in l2:
        # Hyperliquid `l2Book` is a snapshot-per-message feed.
        yield parse_book(update)

    yield gen()
