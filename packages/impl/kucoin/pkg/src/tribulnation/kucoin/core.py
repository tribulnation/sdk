"""Kucoin client ownership, request middleware and inclusive history windows."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing_extensions import (
  AsyncContextManager,
  Awaitable,
  Callable,
  Iterable,
  Iterator,
  TypeVar,
)
from typed_kucoin import KuCoin
from tribulnation.sdk import SDK
from tribulnation.sdk.core import exception_wrapper

T = TypeVar('T')
MILLISECOND = timedelta(milliseconds=1)


def windows(
  start: datetime, end: datetime, width: timedelta
) -> Iterator[tuple[datetime, datetime]]:
  """Tile an inclusive millisecond range without overlapping adjacent queries."""
  while start <= end:
    upper = min(start + width - MILLISECOND, end)
    yield start, upper
    start = upper + MILLISECOND


@dataclass(frozen=True, kw_only=True)
class Mixin(SDK):
  """One owned Typed client with the SDK's error and retry seam."""

  client: KuCoin

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    api_secret: str | None = None,
    api_passphrase: str | None = None,
    *,
    public: bool = False,
    validate: bool = True,
  ):
    """Create a surface, using the client's standard credential defaults."""
    return cls(
      client=KuCoin.new(
        api_key=api_key,
        api_secret=api_secret,
        api_passphrase=api_passphrase,
        public=public,
        validate=validate,
      )
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """The surface owns all transports through the client root."""
    yield self.client

  @SDK.method
  @exception_wrapper()
  async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Translate and retry one request without restarting an account sweep."""
    return await fn()
