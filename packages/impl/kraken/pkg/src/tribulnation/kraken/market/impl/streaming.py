"""Adapting typed-client streams to the SDK's fan-out subscriptions."""

from typing_extensions import (
  Any,
  AsyncIterable,
  AsyncIterator,
  Awaitable,
  Callable,
  TypeVar,
)

from tribulnation.sdk.core import Subscription
from tribulnation.kraken.core import wrap_exceptions

T = TypeVar('T')


def context(
  stream: AsyncIterable[T], unsubscribe: Callable[[], Awaitable[Any]]
) -> Subscription.Context[T]:
  """Wrap a typed-client stream as the `(iterator, unsubscribe)` pair a
  `Subscription` fans out from.

  Iteration is wrapped too, not just the subscribe call: a socket that drops
  mid-stream raises from the `async for`, and that has to reach subscribers as a
  `tribulnation.sdk.core` error like every other failure.
  """

  @wrap_exceptions
  async def iterate() -> AsyncIterator[T]:
    async for item in stream:
      yield item

  return Subscription.Context(iterate(), unsubscribe)
