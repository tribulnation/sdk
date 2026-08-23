"""Utilities for owning groups of asynchronous tasks."""

from collections.abc import AsyncGenerator, Awaitable, Iterable
from contextlib import asynccontextmanager
import asyncio
from typing_extensions import TypeVar

T = TypeVar('T')

@asynccontextmanager
async def managed_tasks(
  awaitables: Iterable[Awaitable[T]],
) -> AsyncGenerator[tuple[asyncio.Future[T], ...]]:
  """Own tasks and drain every task when leaving the context."""
  tasks = tuple(asyncio.ensure_future(awaitable) for awaitable in awaitables)
  try:
    yield tasks
  finally:
    for task in tasks:
      if not task.done():
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
