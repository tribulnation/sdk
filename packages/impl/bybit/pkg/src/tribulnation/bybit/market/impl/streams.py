"""Live order book and fill streams, shared by the spot and linear markets."""

from typing_extensions import AsyncGenerator, AsyncIterable, AsyncIterator
from contextlib import asynccontextmanager

from tribulnation.sdk.core import OverflowPolicy
from tribulnation.sdk.market import Book, Trade

from .mixin import MarketMixin
from .parse import parse_execution


@asynccontextmanager
async def depth_stream(
  self: MarketMixin,
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
) -> AsyncGenerator[AsyncIterable[Book]]:
  """Subscribe to this market's order book.

  `levels` is accepted for interface compatibility and does not resize the shared
  subscription, which every consumer of this symbol reads from; use `depth(levels=...)`
  for a sized snapshot.
  """
  async with self.subscribe_depth(queue_size=queue_size, overflow=overflow) as stream:
    yield stream


@asynccontextmanager
async def trades_stream(
  self: MarketMixin,
  *,
  queue_size: int = 1000,
  overflow: OverflowPolicy = 'fail',
) -> AsyncGenerator[AsyncIterable[Trade]]:
  """Subscribe to this market's own fills.

  Bybit's private `execution` channel is account-wide and carries every category on
  one connection, so the shared subscription is narrowed to this market here.
  """
  async with self.subscribe_executions(
    queue_size=queue_size, overflow=overflow
  ) as stream:

    async def trades() -> AsyncIterator[Trade]:
      async for execution in stream:
        if (
          execution['category'] == self.category
          and execution['symbol'] == self.symbol
          and execution['execType'] == 'Trade'
        ):
          yield parse_execution(execution)

    yield trades()
