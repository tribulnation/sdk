"""Binance client wiring shared by every SDK surface."""

from typing_extensions import (
  AsyncContextManager,
  Awaitable,
  Callable,
  Iterable,
  TypeVar,
)
from dataclasses import dataclass

from tribulnation.sdk import SDK
from tribulnation.sdk.core import exception_wrapper

from typed_binance import Binance

wrap_exceptions = exception_wrapper()

T = TypeVar('T')


@dataclass
class SdkMixin(SDK):
  """Owns the `typed_binance` client every Binance SDK surface calls through."""

  client: Binance
  validate: bool = True

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    secret_key: str | None = None,
    *,
    validate: bool = True,
  ):
    """Create a surface backed by a new Binance client.

    Args:
      api_key: Binance API key. Defaults to `BINANCE_API_KEY`.
      secret_key: Binance API secret. Defaults to `BINANCE_SECRET_KEY`.
      validate: Validate responses against the typed client's schemas.
    """
    client = Binance.new(api_key=api_key, secret_key=secret_key, validate=validate)
    return cls(client=client, validate=validate)

  @SDK.method
  @wrap_exceptions
  async def call_binance(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Call Binance under the SDK exception wrapper.

    One request per call, so a sweep's retries and tracing span apply per page rather
    than restarting the whole sweep.
    """
    return await fn()

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield from super().resources()
    yield self.client
