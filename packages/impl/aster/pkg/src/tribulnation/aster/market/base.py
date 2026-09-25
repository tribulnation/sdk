"""Shared stream adapters for Aster's two native exchanges."""

from contextlib import asynccontextmanager
from typing_extensions import AsyncGenerator, AsyncIterable
from tribulnation.sdk.core import OverflowPolicy, SDK
from tribulnation.sdk.market import Book, Trade
from ..core import Scope, SharedMixin


class ExchangeMixin(SharedMixin):
  """Bounded subscribers share a native stream without invalidating each other's keys."""

  @property
  def exchange_id(self) -> Scope:
    """Select the native exchange transport."""
    raise NotImplementedError

  @SDK.method
  @asynccontextmanager
  async def depth_stream(
    self,
    market_id: str,
    /,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
  ) -> AsyncGenerator[AsyncIterable[Book], None]:
    """Read complete native top-20 snapshots, trimmed independently per subscriber."""
    if levels is not None and not 1 <= levels <= 20:
      raise NotImplementedError('Aster partial-depth streams support 1-20 levels')

    async def limited(stream: AsyncIterable[Book]) -> AsyncIterable[Book]:
      """Apply the requested depth without mutating another subscriber's book."""
      async for book in stream:
        yield book if levels is None else book.limit(levels)

    async with self.shared.book_subscription(self.exchange_id, market_id).subscribe(
      queue_size=queue_size, overflow=overflow
    ) as stream:
      yield limited(stream)

  @SDK.method
  @asynccontextmanager
  async def trades_stream(
    self,
    market_id: str,
    /,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
  ) -> AsyncGenerator[AsyncIterable[Trade], None]:
    """Read this symbol's native fills from one shared account stream."""

    async def selected(
      stream: AsyncIterable[tuple[str, Trade]],
    ) -> AsyncIterable[Trade]:
      """Keep the selected symbol's events without manufacturing history."""
      async for symbol, trade in stream:
        if symbol == market_id:
          yield trade

    async with self.shared.trade_subscription(self.exchange_id).subscribe(
      queue_size=queue_size, overflow=overflow
    ) as stream:
      yield selected(stream)
