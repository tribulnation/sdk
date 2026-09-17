"""Shared Deribit ownership and per-request SDK middleware."""

from functools import cached_property

from dataclasses import dataclass
from typing_extensions import (
  AsyncContextManager,
  Awaitable,
  Callable,
  Iterable,
  TypeVar,
)
from typed_deribit import Deribit
from tribulnation.sdk import SDK
from tribulnation.sdk.core import ManagedResource, exception_wrapper

T = TypeVar('T')


@dataclass(frozen=True, kw_only=True)
class Mixin(SDK):
  """One owned client, shared by all methods on a surface."""

  client: Deribit

  @classmethod
  def new(
    cls,
    client_id: str | None = None,
    client_secret: str | None = None,
    *,
    public: bool = False,
    testnet: bool = False,
    validate: bool = True,
  ):
    """Create a client; testnet chooses separate hosts and credential defaults."""
    return cls(
      client=Deribit.new(
        client_id=client_id,
        client_secret=client_secret,
        public=public,
        testnet=testnet,
        validate=validate,
      )
    )

  @cached_property
  def client_resource(self) -> ManagedResource[object]:
    """Own client with the venue's entry and cleanup policies."""
    return ManagedResource(
      resource=self.client,
      wrap_enter=exception_wrapper(),
      wrap_exit=exception_wrapper(),
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """The surface owns its client, including its lazy socket transport."""
    yield self.client_resource

  @SDK.method
  @exception_wrapper()
  async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Retry and translate one request rather than restarting an entire sweep."""
    return await fn()
