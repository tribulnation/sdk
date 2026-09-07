"""A failed page of a paginated sweep must replay alone, not restart the sweep.

`@SDK.method`'s retry middleware only binds to coroutine functions, so the per-page
`call_app` shim is what makes an individual page fetch retriable. Fetch the pages
outside it and a failure on page 7 of 12 costs the caller all twelve. No live venue can
be made to fail one page on demand.
"""

from typing_extensions import Any, Awaitable, Callable, Sequence, TypeVar, cast

from typed_core import PaginatedResponse

from typed_coinbase import Coinbase

from tribulnation.coinbase.core.mixin import Shared
from tribulnation.coinbase.market import SpotExchange

T = TypeVar('T')


class FakeEndpoint:
  """One endpoint whose `*_paged` variant serves a canned page list."""

  def __init__(
    self, next: Callable[[str], Awaitable[tuple[Sequence[Any], str | None]]]
  ):
    self.next = next

  def list_paged(self, *args: Any, **kwargs: Any) -> PaginatedResponse[Any, str]:
    return PaginatedResponse('', self.next)


class FakeChain:
  """Resolves any attribute path down to the endpoint it was built with."""

  def __init__(self, endpoint: FakeEndpoint):
    self.endpoint = endpoint

  def __getattr__(self, name: str) -> Any:
    if name.endswith('_paged'):
      return getattr(self.endpoint, name)
    return self


async def test_a_failing_page_is_the_only_thing_replayed() -> None:
  """Page 1 of 3 fails once; page 0 must not be fetched a second time."""
  attempts: list[int] = []

  async def next(cursor: str) -> tuple[Sequence[Any], str | None]:
    index = int(cursor or '0')
    attempts.append(index)
    if index == 1 and attempts.count(1) == 1:
      raise TimeoutError('transient')
    return [{'product_id': f'P{index}-USD'}], (str(index + 1) if index < 2 else None)

  class RetryingExchange(SpotExchange):
    """A spot exchange retrying each page fetch once."""

    async def call_app(self, fn: Callable[[], Awaitable[T]]) -> T:
      try:
        return await fn()
      except TimeoutError:
        return await fn()

  client = cast(Coinbase, FakeChain(FakeEndpoint(next)))
  exchange = RetryingExchange(shared=Shared(client=client))

  assert list(await exchange.markets()) == ['P0-USD', 'P1-USD', 'P2-USD']
  assert attempts == [0, 1, 1, 2], 'page 1 replayed alone; page 0 fetched once'
