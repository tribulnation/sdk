"""Extended client ownership, request middleware, venue constants and cached markets."""

from dataclasses import dataclass, field
from datetime import timedelta
from functools import cached_property
import asyncio

from typing_extensions import (
  AsyncContextManager,
  Awaitable,
  Callable,
  Iterable,
  Literal,
  Mapping,
  TypedDict,
  TypeVar,
)
from typed_extended import Extended
from typed_extended.core.networks import Network
from typed_extended.account.schemas import AccountLeverage, Position as PositionRow
from typed_extended.info.markets import Market as MarketRow
from tribulnation.sdk import SDK
from tribulnation.sdk.core import (
  SharedReads,
  AuthError,
  ManagedResource,
  Subscription,
  exception_wrapper,
)
from tribulnation.sdk.market import Book, Trade

T = TypeVar('T')
VenueId = Literal['extended', 'extended_testnet']

FUNDING_INTERVAL = timedelta(hours=1)
"""Extended applies funding once an hour; the rate is re-estimated every minute."""
ORDER_LIFETIME: Mapping[Network, timedelta] = {
  'mainnet': timedelta(days=90),
  'testnet': timedelta(days=28),
}
"""The longest expiry a resting order may carry on each network."""
EXPIRY_MARGIN = timedelta(minutes=1)
"""Kept off the longest expiry, so a client clock slightly ahead of the venue's does not
push an order past the network's limit."""


class Settings(TypedDict, total=False):
  """Extended settings, under `settings['extended']`."""

  time_in_force: Literal['IOC']
  """Send a `LIMIT` order immediate-or-cancel instead of good-till-time: it fills what it
  can at the limit price or better and cancels the rest. `POST_ONLY` and `MARKET` orders
  raise `ValueError` when it is set."""


COLLATERAL = 'USD'
"""The deployment's one collateral asset: margin, PnL, trading fees and funding settle in
it, and every market names it as `collateralAssetName`."""
LISTED = frozenset({'ACTIVE', 'REDUCE_ONLY', 'REDUCE_ONLY_OI', 'PRELISTED'})
"""Market statuses `markets()` lists: every perpetual that is not delisted or disabled
(`rules().api` says which trade). `REDUCE_ONLY_OI` is reduce-only while open interest is
above the market's `openInterestLimit`."""


def network_venue_id(network: Network) -> VenueId:
  """The venue ID of a deployment: testnet reports `'extended_testnet'`."""
  return 'extended' if network == 'mainnet' else 'extended_testnet'


@dataclass(frozen=True, kw_only=True)
class Shared(SDK):
  """Own one client for one sub-account; cache markets and share reads and streams."""

  client: Extended
  venue_id: VenueId = 'extended'
  """The deployment this client is connected to, as a venue ID."""
  account_id: str | None = None
  """Root SDK account key; `None` when built directly, reporting `venue_id` instead."""
  markets: dict[str, MarketRow] = field(default_factory=dict[str, MarketRow])
  """Every market of the deployment (perpetual and spot, delisted included), by name."""
  lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  books: dict[str, Subscription[Book]] = field(
    default_factory=dict[str, Subscription[Book]]
  )
  """One shared upstream book per market."""
  fills: dict[str, Subscription[Trade]] = field(
    default_factory=dict[str, Subscription[Trade]]
  )
  """One shared account stream per market, filtered to its fills."""
  reads: SharedReads = field(default_factory=SharedReads)
  """Reads shared between markets and concurrent callers (`leverage()`, the all-market
  reads of `remaining_position_limit()`)."""

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    stark_private_key: str | None = None,
    stark_public_key: str | None = None,
    vault: int | str | None = None,
    *,
    network: Network = 'mainnet',
    public: bool = False,
    validate: bool = True,
    account_id: str | None = None,
  ):
    """Build a client for one sub-account, from explicit credentials or the client's
    `EXTENDED_*` defaults (`EXTENDED_TESTNET_*` on testnet).

    Args:
      api_key: The sub-account's API key: every account read, and cancellations.
      stark_private_key: The sub-account's Stark private key, needed to place orders.
      stark_public_key: Its Stark public key, checked against the private key.
      vault: The sub-account's vault (position id), needed with the Stark key.
      network: Extended deployment.
      public: Skip credentials: public market data only.
      validate: Validate responses.
      account_id: Root SDK account key, the first segment of every market ID;
        defaults to the venue ID.
    """
    return cls(
      venue_id=network_venue_id(network),
      account_id=account_id,
      client=Extended.new(
        network=network,
        api_key=api_key,
        stark_private_key=stark_private_key,
        stark_public_key=stark_public_key,
        vault=vault,
        public=public,
        validate=validate,
      ),
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
    """Translate and retry one request."""
    return await fn()

  @property
  def network(self) -> Network:
    """The client's deployment."""
    return self.client.network.name

  def require_signer(self):
    """Check the client can sign orders, before building one.

    Raises:
      AuthError: The client has no Stark private key (public, or an API key alone).
    """
    credentials = self.client.credentials
    if credentials is None or credentials.stark is None:
      raise AuthError(
        "Extended trading needs the sub-account's Stark private key and vault; "
        'an API key alone only reads and cancels'
      )

  async def load_markets(self, *, refetch: bool = False) -> Mapping[str, MarketRow]:
    """Every market of the deployment, from one request, cached until `refetch`."""
    async with self.lock:
      if refetch or not self.markets:
        rows = await self.call(self.client.info.markets)
        self.markets.clear()
        self.markets.update((m['name'], m) for m in rows)
    return self.markets

  async def perp(self, name: str, *, refetch: bool = False) -> MarketRow:
    """One perpetual market's cached row.

    Raises:
      ValueError: The deployment has no perpetual market of that name.
    """
    markets = await self.load_markets(refetch=refetch)
    row = markets.get(name)
    if row is None or row['type'] != 'PERPETUAL':
      raise ValueError(f'Unknown Extended perpetual market: {name!r}')
    return row

  async def live_market(self, name: str, *, ttl: timedelta | None) -> MarketRow:
    """One perpetual's row with live statistics, from one all-market request shared
    for `ttl` (see `SharedReads`).

    Raises:
      ValueError: The deployment has no perpetual market of that name.
    """
    rows = await self.reads.read(
      ('markets',), lambda: self.call(self.client.info.markets), ttl=ttl
    )
    for row in rows:
      if row['name'] == name and row['type'] == 'PERPETUAL':
        return row
    raise ValueError(f'Unknown Extended perpetual market: {name!r}')

  async def positions(self, *, ttl: timedelta | None) -> list[PositionRow]:
    """Every open position of the sub-account, from one request shared for `ttl`."""
    return await self.reads.read(
      ('positions',), lambda: self.call(self.client.account.positions), ttl=ttl
    )

  async def leverages(self, *, ttl: timedelta | None) -> list[AccountLeverage]:
    """The sub-account's leverage on every perpetual, from one request shared for `ttl`."""
    return await self.reads.read(
      ('leverage',), lambda: self.call(self.client.account.leverage), ttl=ttl
    )

  async def fresh(self, name: str) -> MarketRow:
    """One market's row with live statistics, from its own request.

    Raises:
      ValueError: The deployment has no perpetual market of that name.
    """
    await self.perp(name)
    rows = await self.call(lambda: self.client.info.markets([name]))
    if not rows:
      raise ValueError(f'Unknown Extended perpetual market: {name!r}')
    return rows[0]
