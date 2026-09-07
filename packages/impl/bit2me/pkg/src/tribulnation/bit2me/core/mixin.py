"""Shared plumbing for every Bit2Me SDK surface: the per-request seam and the
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

from typed_bit2me import Bit2Me

from .exc import wrap_exceptions

T = TypeVar('T')


class Calls(SDK):
  """The seam every single Bit2Me request is routed through.

  One request per invocation, so retry middleware bound by `@SDK.method` retries
  that request rather than whatever sweep is driving it: a failed page 7 of 12 is
  refetched on its own instead of restarting the walk at page 1.
  """

  @SDK.method
  @wrap_exceptions
  async def call_bit2me(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Call Bit2Me under the SDK exception wrapper."""
    return await fn()


@dataclass(frozen=True, kw_only=True)
class Mixin(Calls):
  """Base for the Bit2Me surfaces backed by one plain `typed_bit2me` client."""

  client: Bit2Me

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    api_secret: str | None = None,
    *,
    public: bool = False,
    validate: bool = True,
    **fields: Any,
  ):
    """Build a surface around a fresh Bit2Me client.

    Args:
      api_key: Bit2Me API key; read from `BIT2ME_API_KEY` when omitted.
      api_secret: Bit2Me API secret; read from `BIT2ME_SECRET_KEY` when omitted.
      public: Build a public-only client, with no credentials at all.
      validate: Validate responses.
      **fields: Any other field the concrete surface declares, e.g. the wallet's
        `quote_addresses`.
    """
    return cls(
      client=Bit2Me.new(
        api_key=api_key, api_secret=api_secret, public=public, validate=validate
      ),
      **fields,
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield from super().resources()
    yield self.client
