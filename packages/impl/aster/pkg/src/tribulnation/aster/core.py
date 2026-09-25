"""Aster client ownership, cached symbol metadata and the SDK request seam."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import cached_property
import asyncio
from typing_extensions import (
  AsyncContextManager,
  AsyncIterable,
  AsyncIterator,
  Awaitable,
  Callable,
  Hashable,
  Iterable,
  Literal,
  TypeVar,
)
from eth_utils.address import is_address, to_checksum_address
from typed_aster import Aster
from typed_aster.core.auth import Credentials, parse_wallet
from typed_aster.core.base import ChainClients, SurfaceClients
from typed_aster.core.transport.bapi import BapiClient
from typed_aster.futures.market.exchange_info import FuturesSymbol
from typed_aster.spot.market.exchange_info import SpotSymbol
from tribulnation.sdk.core import (
  AuthError,
  ManagedResource,
  OverflowPolicy,
  SDK,
  Subscription,
  exception_wrapper,
)
from tribulnation.sdk.market import Book, Collateral, Trade

T = TypeVar('T')
U = TypeVar('U')
K = TypeVar('K', bound=Hashable)
Scope = Literal['spot', 'perp']
wrap_exceptions = exception_wrapper()


@wrap_exceptions
def new_client(
  *,
  user: str | None,
  signer: str | None,
  public: bool,
  mainnet: bool,
  validate: bool,
) -> Aster:
  """Build transports signed by the trading agent only.

  `Aster.new` also reads the main wallet's key from the environment; the SDK never
  needs it, so credentials are built here from the arguments alone.
  """
  credentials = None
  if not public:
    if not user or not signer:
      raise AuthError('Aster requires `user` and `signer`, or `public=True`')
    if not is_address(user):
      raise AuthError('Aster `user` must be an EVM wallet address')
    credentials = Credentials(
      user=to_checksum_address(user), agent=parse_wallet(signer)
    )

  def surface(name: Literal['futures', 'spot', 'prediction'], signed: bool):
    """Build one surface's transports for the selected network."""
    return SurfaceClients.build(
      name,
      credentials=credentials if signed else None,
      mainnet=mainnet,
      validate=validate,
    )

  return Aster(
    futures_clients=surface('futures', True),
    spot_clients=surface('spot', True),
    prediction_clients=surface('prediction', False),
    chain_clients=ChainClients.build(credentials=None, validate=validate),
    bapi_client=BapiClient(validate=validate),
  )


@dataclass(frozen=True, kw_only=True)
class Shared(SDK):
  """Own one client, its symbol metadata and the account's shared streams."""

  client: Aster
  mainnet: bool
  spot: dict[str, SpotSymbol] = field(default_factory=dict[str, SpotSymbol])
  perp: dict[str, FuturesSymbol] = field(default_factory=dict[str, FuturesSymbol])
  lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  books: dict[tuple[Scope, str], Subscription[Book]] = field(
    default_factory=dict[tuple[Scope, str], Subscription[Book]]
  )
  trades: dict[Scope, Subscription[tuple[str, Trade]]] = field(
    default_factory=dict[Scope, Subscription[tuple[str, Trade]]]
  )

  @property
  def venue_id(self) -> str:
    """The network-specific venue ID."""
    return 'aster' if self.mainnet else 'aster_testnet'

  @cached_property
  def client_resource(self) -> ManagedResource[object]:
    """Own the client with the venue's entry and cleanup policies."""
    return ManagedResource(
      resource=self.client, wrap_enter=wrap_exceptions, wrap_exit=wrap_exceptions
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """The client root owns every transport."""
    yield self.client_resource

  @SDK.method
  @wrap_exceptions
  async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Translate and retry one request or one paginator page."""
    return await fn()

  async def spot_symbols(self, *, refetch: bool = False) -> dict[str, SpotSymbol]:
    """Cache the spot symbols currently open for trading."""
    async with self.lock:
      if refetch or not self.spot:
        info = await self.call(self.client.spot.market.exchange_info)
        self.spot.clear()
        self.spot.update(
          (r['symbol'], r) for r in info['symbols'] if r['status'] == 'TRADING'
        )
    return self.spot

  async def perp_symbols(self, *, refetch: bool = False) -> dict[str, FuturesSymbol]:
    """Cache the perpetual contracts currently open for trading."""
    async with self.lock:
      if refetch or not self.perp:
        info = await self.call(self.client.futures.market.exchange_info)
        self.perp.clear()
        self.perp.update(
          (r['symbol'], r)
          for r in info['symbols']
          if r['status'] == 'TRADING' and r['contractType'] == 'PERPETUAL'
        )
    return self.perp

  async def cross_collateral(self) -> Collateral:
    """Read the perpetual cross-margin bucket's equity and available balance."""
    row = await self.call(self.client.futures.account.info_with_join_margin)
    return Collateral(
      equity=row['totalMarginBalance'], free_collateral=row['availableBalance']
    )

  @asynccontextmanager
  async def stream(
    self,
    subscriptions: dict[K, Subscription[T]],
    key: K,
    connect: Callable[[], Awaitable[Subscription.Context[T]]],
    *,
    select: Callable[[T], U | None],
    queue_size: int,
    overflow: OverflowPolicy,
  ) -> AsyncIterator[AsyncIterable[U]]:
    """Subscribe to one shared upstream, mapping or dropping items per subscriber.

    The upstream opens with its first subscriber and closes with its last.
    """
    if key not in subscriptions:
      subscriptions[key] = Subscription(connect)
    async with subscriptions[key].subscribe(
      queue_size=queue_size, overflow=overflow
    ) as upstream:

      async def selected() -> AsyncIterator[U]:
        """Yield this subscriber's view of each shared item."""
        async for item in upstream:
          if (value := select(item)) is not None:
            yield value

      yield selected()


@dataclass(frozen=True, kw_only=True)
class Public(SDK):
  """Share one resource owner across venue, exchange, market and report objects."""

  shared: Shared

  @classmethod
  def new(
    cls,
    *,
    user: str | None = None,
    signer: str | None = None,
    public: bool = False,
    mainnet: bool = True,
    validate: bool = True,
  ):
    """Create a surface over a new client.

    Args:
      user: Main wallet address (the Aster account).
      signer: Private key of the trading agent (API wallet) registered for `user`.
      public: Build a credential-free client for market data.
      mainnet: Use mainnet when true, testnet when false.
      validate: Validate responses against the typed client's schemas.
    """
    client = new_client(
      user=user, signer=signer, public=public, mainnet=mainnet, validate=validate
    )
    return cls(shared=Shared(client=client, mainnet=mainnet))

  @property
  def client(self) -> Aster:
    """The shared typed client."""
    return self.shared.client

  @property
  def venue_id(self) -> str:
    """The network-specific venue ID."""
    return self.shared.venue_id

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """Enter the shared owner through the SDK lifecycle."""
    yield self.shared
