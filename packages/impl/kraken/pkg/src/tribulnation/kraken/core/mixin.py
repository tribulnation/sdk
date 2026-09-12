"""Shared plumbing for every Kraken SDK surface: the per-request seam and the
single-client base the non-market surfaces are built on."""

from typing_extensions import (
  Any,
  AsyncContextManager,
  Awaitable,
  Callable,
  Iterable,
  TypeVar,
)
from dataclasses import dataclass

from tribulnation.sdk.core import SDK

from typed_kraken import Kraken

from .exc import wrap_exceptions

T = TypeVar('T')


class Calls(SDK):
  """The seam every single Kraken request is routed through.

  One request per invocation, so retry middleware bound by `@SDK.method` retries
  that request rather than whatever sweep is driving it: a failed ledger page 7 of
  12 is refetched on its own instead of restarting the walk at page 1.
  """

  @SDK.method
  @wrap_exceptions
  async def call_kraken(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Call Kraken under the SDK exception wrapper."""
    return await fn()


@dataclass(frozen=True, kw_only=True)
class Mixin(Calls):
  """Base for the Kraken surfaces backed by one plain `typed_kraken` client.

  The client owns one HTTP transport and two WebSocket v2 sockets, all of which
  connect lazily on first use, so yielding it from `resources()` costs nothing for a
  surface that only ever reads REST.
  """

  client: Kraken

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    private_key: str | None = None,
    *,
    public: bool = False,
    validate: bool = True,
    **fields: Any,
  ):
    """Build a surface around a fresh Kraken Spot client.

    Args:
      api_key: Kraken API key; read from `KRAKEN_API_KEY` when omitted.
      private_key: Kraken private key; read from `KRAKEN_PRIVATE_KEY` when omitted.
      public: Build a credential-free client, usable only for public endpoints.
      validate: Validate responses.
      **fields: Any other field the concrete surface declares.
    """
    return cls(
      client=Kraken.new(
        api_key=api_key, private_key=private_key, public=public, validate=validate
      ),
      **fields,
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield from super().resources()
    yield self.client
