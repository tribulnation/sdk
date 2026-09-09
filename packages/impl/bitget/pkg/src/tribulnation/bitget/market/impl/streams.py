"""Live order book and fill streams, shared by the spot and perpetual markets."""

from typing_extensions import AsyncGenerator, AsyncIterable, AsyncIterator
from contextlib import asynccontextmanager

from tribulnation.sdk.core import OverflowPolicy
from tribulnation.sdk.market import Book, Trade

from .mixin import MarketMixin
from .parse import parse_classic_stream_fill, parse_uta_stream_fill


@asynccontextmanager
async def depth_stream(
  self: MarketMixin,
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
) -> AsyncGenerator[AsyncIterable[Book]]:
  """Subscribe to this market's order book.

  The shared subscription runs at full depth for every consumer of this symbol;
  `levels` trims each delivered book rather than resizing the upstream.
  """
  async with self.subscribe_depth(queue_size=queue_size, overflow=overflow) as stream:
    if levels is None:
      yield stream
    else:

      async def limited() -> AsyncIterator[Book]:
        async for book in stream:
          yield book.limit(levels)

      yield limited()


@asynccontextmanager
async def trades_stream(
  self: MarketMixin,
  *,
  queue_size: int = 1000,
  overflow: OverflowPolicy = 'fail',
) -> AsyncGenerator[AsyncIterable[Trade]]:
  """Subscribe to this market's own fills.

  The private channel differs by account mode: Classic v2 subscribes per product line
  and symbol, UTA v3 serves the whole unified account on one channel that is narrowed
  to this market here.
  """
  if await self.is_uta():
    async with self.subscribe_uta_fills(
      queue_size=queue_size, overflow=overflow
    ) as stream:

      async def uta_trades() -> AsyncIterator[Trade]:
        async for fill in stream:
          # The REST twin of this row documents both casings of `category` as valid.
          if fill['category'].upper() == self.product and fill['symbol'] == self.symbol:
            yield parse_uta_stream_fill(fill)

      yield uta_trades()
  else:
    async with self.subscribe_classic_fills(
      queue_size=queue_size, overflow=overflow
    ) as stream:

      async def classic_trades() -> AsyncIterator[Trade]:
        async for fill in stream:
          if fill['symbol'] == self.symbol:
            yield parse_classic_stream_fill(fill)

      yield classic_trades()
