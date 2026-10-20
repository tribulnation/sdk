"""Margin Trade client ownership, request middleware, venue constants and cached metadata."""

from functools import cached_property
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
import asyncio

from typing_extensions import (
  AsyncContextManager,
  Awaitable,
  Callable,
  Iterable,
  Literal,
  TypeVar,
)
from typed_margintrade import MarginTrade
from typed_margintrade.core.auth import address as key_address
from typed_margintrade.schemas import PerpUniverseItem
from tribulnation.sdk import SDK
from tribulnation.sdk.core import (
  AuthError,
  ManagedResource,
  Subscription,
  exception_wrapper,
)
from tribulnation.sdk.market import Book

T = TypeVar('T')

USDC = 'USDC'
"""The collateral asset: perpetual margin, PnL, fees and funding settle in USDC."""
FUNDING_INTERVAL = timedelta(hours=1)
"""Margin Trade settles funding every hour."""
PRICE_DECIMALS = 6
"""Price step is `10 ** -(6 - szDecimals)` (the venue's Markets table: BTC 0.1 with 5 size
decimals, SOL 0.0001 with 2); prices are also limited to 5 significant figures."""
MAX_BAND = Decimal('0.2')
"""The oracle price band is `1 / (2 * maxLeverage)`, capped at 20%."""

VenueId = Literal['margintrade', 'margintrade_testnet']


@dataclass(frozen=True, kw_only=True)
class Shared(SDK):
  """Own one client; cache the perpetual universe and shared book fan-outs."""

  client: MarginTrade
  venue_id: VenueId = 'margintrade'
  """The network this client is connected to, as a venue ID."""
  account_id: str | None = None
  """Root SDK account key; `None` when built directly, reporting `venue_id` instead."""
  address: str | None = None
  """Account whose public reads (positions, orders, fills, funding) are served."""
  universe: dict[str, PerpUniverseItem] = field(
    default_factory=dict[str, PerpUniverseItem]
  )
  """Perpetual markets by coin name."""
  lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  books: dict[str, Subscription[Book]] = field(
    default_factory=dict[str, Subscription[Book]]
  )
  """One shared `l2Book` upstream per coin."""
  leverages: dict[str, Decimal] = field(default_factory=dict[str, Decimal])
  """The account's leverage per market, filled by `leverage()`."""

  @classmethod
  def new(
    cls,
    address: str | None = None,
    *,
    private_key: str | None = None,
    mainnet: bool = True,
    public: bool = False,
    validate: bool = True,
    account_id: str | None = None,
    rest_url: str | None = None,
    ws_url: str | None = None,
  ):
    """Build a client from an address (public account reads) and an optional key.

    Args:
      address: Account to read; defaults to the key's own account.
      private_key: Ed25519 private key (hex or base58).
      mainnet: Use mainnet when true, testnet when false.
      public: Allow construction without a key.
      validate: Validate responses.
      account_id: Root SDK account key, the first segment of every market ID.
      rest_url: HTTP API root override.
      ws_url: WebSocket URL override.
    """
    client = MarginTrade.new(
      private_key,
      mainnet=mainnet,
      public=public or private_key is None,
      validate=validate,
      base_url=rest_url,
      ws_url=ws_url,
    )
    resolved = (
      address
      if address is not None
      else (key_address(client.key) if client.key is not None else None)
    )
    return cls(
      client=client,
      venue_id='margintrade' if mainnet else 'margintrade_testnet',
      account_id=account_id,
      address=resolved,
    )

  @cached_property
  def client_resource(self) -> ManagedResource[object]:
    """Own the client with the SDK's exception translation on entry and exit."""
    return ManagedResource(
      resource=self.client,
      wrap_enter=exception_wrapper(),
      wrap_exit=exception_wrapper(),
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """The client root owns every transport."""
    yield self.client_resource

  @SDK.method
  @exception_wrapper()
  async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Translate one request's exceptions."""
    return await fn()

  @property
  def user(self) -> str:
    """The account address account reads use.

    Raises:
      AuthError: Neither an address nor a key is configured.
    """
    if self.address is None:
      raise AuthError(
        'Account-scoped Margin Trade data needs an `address` or a private key'
      )
    return self.address

  async def load_universe(self, *, refetch: bool = False):
    """Cache every perpetual market's static descriptor."""
    async with self.lock:
      if refetch or not self.universe:
        meta = await self.call(self.client.info.meta)
        self.universe.clear()
        self.universe.update((m['name'], m) for m in meta['universe'])

  async def asset(self, coin: str, *, refetch: bool = False) -> PerpUniverseItem:
    """One perpetual market's descriptor.

    Raises:
      ValueError: The coin is not a listed perpetual.
    """
    await self.load_universe(refetch=refetch)
    if coin not in self.universe:
      raise ValueError(f'Unknown Margin Trade perpetual market: {coin!r}')
    return self.universe[coin]
