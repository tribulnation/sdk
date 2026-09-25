"""Aster client ownership, isolated credentials and per-request SDK policies."""

from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from functools import cached_property
import asyncio
import os
from typing_extensions import (
  AsyncContextManager,
  Awaitable,
  Callable,
  Iterable,
  Literal,
  TypeVar,
)
from eth_utils.address import is_address, to_checksum_address
from typed_aster import Aster
from typed_aster.core.auth import Credentials, parse_wallet
from typed_aster.core.base import ChainClients, SurfaceClients
from tribulnation.sdk.core import (
  AuthError,
  ManagedResource,
  SDK,
  Subscription,
  exception_wrapper,
)
from tribulnation.sdk.market import Book, Trade

T = TypeVar('T')
Scope = Literal['spot', 'perp']
wrap_exceptions = exception_wrapper()


@wrap_exceptions
def new_client(
  *, user: str | None, signer: str | None, public: bool, mainnet: bool
) -> Aster:
  """Build validated transports without falling back to another network's secrets.

  Only the trading agent is used. Management and main-wallet signing credentials
  are deliberately absent from these SDK surfaces.
  """
  credentials = None
  if not public:
    prefix = 'ASTER' if mainnet else 'TEST_ASTER'
    user = user or os.getenv(f'{prefix}_USER')
    signer = signer or os.getenv(f'{prefix}_SIGNER_PRIVATE_KEY')
    if not user or not signer:
      raise AuthError(
        f'Provide user and signer, or {prefix}_USER and {prefix}_SIGNER_PRIVATE_KEY'
      )
    if not is_address(user):
      raise AuthError('Aster user must be an EVM wallet address')
    credentials = Credentials(
      user=to_checksum_address(user), agent=parse_wallet(signer)
    )
  return Aster(
    futures_clients=SurfaceClients.build(
      'futures', credentials=credentials, mainnet=mainnet, validate=True
    ),
    spot_clients=SurfaceClients.build(
      'spot', credentials=credentials, mainnet=mainnet, validate=True
    ),
    prediction_clients=SurfaceClients.build(
      'prediction', credentials=credentials, mainnet=mainnet, validate=True
    ),
    chain_clients=ChainClients.build(credentials=None, validate=True),
  )


class Calls(SDK):
  """Translate each request before SDK retry middleware sees its failure."""

  @SDK.method
  @wrap_exceptions
  async def call_aster(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Run one native request or one typed paginator page."""
    return await fn()


async def close_subscription(subscription: Subscription[T]):
  """Release an active shared subscription when its owning SDK context exits."""
  async with subscription.lock:
    pump, context = subscription.pump, subscription.ctx
    subscription.pump = subscription.ctx = None
    inboxes = list(subscription.subscribers)
    subscription.subscribers.clear()
  try:
    if pump is not None:
      pump.cancel()
      with suppress(asyncio.CancelledError):
        await pump
  finally:
    try:
      if context is not None:
        await context.unsubscribe()
    finally:
      for inbox in inboxes:
        inbox.close()


@asynccontextmanager
async def closing_streams(shared: 'Shared'):
  """Close lazy sockets and listen keys before releasing the HTTP client."""
  try:
    yield
  finally:
    results = await asyncio.gather(
      *(close_subscription(s) for s in shared.books.values()),
      *(close_subscription(s) for s in shared.trades.values()),
      return_exceptions=True,
    )
    for result in results:
      if isinstance(result, BaseException):
        raise result


@dataclass(kw_only=True)
class Shared(Calls):
  """One client and shared subscriptions for all objects belonging to this account."""

  client: Aster
  books: dict[tuple[Scope, str], Subscription[Book]] = field(
    default_factory=dict[tuple[Scope, str], Subscription[Book]]
  )
  trades: dict[Scope, Subscription[tuple[str, Trade]]] = field(
    default_factory=dict[Scope, Subscription[tuple[str, Trade]]]
  )

  @property
  def venue_id(self) -> str:
    """Preserve network identity in direct SDK objects and report provenance."""
    return 'aster' if self.client.futures.client.mainnet else 'aster_testnet'

  @cached_property
  def client_resource(self) -> ManagedResource[object]:
    """Translate entry/cleanup errors without retrying the entire lifecycle."""
    return ManagedResource(
      resource=self.client, wrap_enter=wrap_exceptions, wrap_exit=wrap_exceptions
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """Own the client once, and close subscriptions first in reverse order."""
    yield self.client_resource
    yield ManagedResource(
      resource=closing_streams(self),
      wrap_enter=wrap_exceptions,
      wrap_exit=wrap_exceptions,
    )

  def book_subscription(self, scope: Scope, symbol: str) -> Subscription[Book]:
    """Reuse the same complete top-20 upstream for every subscriber to a symbol."""
    from .streams import connect_books

    key = (scope, symbol)
    if key not in self.books:
      self.books[key] = Subscription(lambda: connect_books(self, scope, symbol))
    return self.books[key]

  def trade_subscription(self, scope: Scope) -> Subscription[tuple[str, Trade]]:
    """Own one account listen key per venue, shared across symbols/subscribers."""
    from .streams import connect_trades

    if scope not in self.trades:
      self.trades[scope] = Subscription(lambda: connect_trades(self, scope))
    return self.trades[scope]


@dataclass(frozen=True, kw_only=True)
class SharedMixin(Calls):
  """Let venue, exchange, market and report objects borrow the same owned state."""

  shared: Shared

  @classmethod
  def new(
    cls,
    *,
    user: str | None = None,
    signer: str | None = None,
    public: bool = False,
    mainnet: bool = True,
  ):
    """Construct a validated Aster surface for the selected network."""
    return cls(
      shared=Shared(
        client=new_client(user=user, signer=signer, public=public, mainnet=mainnet)
      )
    )

  @property
  def client(self) -> Aster:
    """The shared native typed client."""
    return self.shared.client

  @property
  def venue_id(self) -> str:
    """The account's network-specific venue ID."""
    return self.shared.venue_id

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """Delegate lifetime to the single shared owner."""
    yield self.shared
