"""RISEx client ownership, request middleware, venue constants and cached markets."""

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from functools import cached_property
import asyncio
import secrets

from typing_extensions import (
  AsyncContextManager,
  Awaitable,
  Callable,
  Iterable,
  Literal,
  Mapping,
  TypeVar,
)
from typed_risex import RISEx
from typed_risex.core.networks import Network
from typed_risex.markets.all import MarketInfo
from typed_risex.streams.fills import FillsMessage
from tribulnation.sdk import SDK
from tribulnation.sdk.core import (
  AuthError,
  ManagedResource,
  SharedReads,
  Subscription,
  exception_wrapper,
)
from tribulnation.sdk.market import Book

T = TypeVar('T')
VenueId = Literal['risex', 'risex_testnet']
"""RISEx's venue IDs: mainnet, and testnet as a separate venue."""

wrap_exceptions = exception_wrapper()

COLLATERAL = 'USDC'
"""The one collateral asset: margin, PnL, trading fees and funding all settle in it."""
WAD = Decimal(10**18)
"""The scale of the on-chain integers some endpoints return (`account.positions`, the
fills of an IOC placement)."""
FUNDING_INTERVAL = timedelta(hours=1)
"""RISEx settles funding once an hour (every market's `funding_interval`)."""
CLIENT_ORDER_IDS = 2**63
"""Client order ids are drawn below this: the venue's `client_order_id` is an unsigned
integer, echoed back as a decimal string, and a signed 64-bit range is safe for every
consumer."""


def network_venue_id(network: Network) -> VenueId:
  """The venue ID of a deployment: testnet reports `'risex_testnet'`."""
  return 'risex' if network == 'mainnet' else 'risex_testnet'


def wad(value: int) -> Decimal:
  """A 1e18-scaled on-chain integer as a decimal."""
  return Decimal(value) / WAD


def random_client_order_id() -> str:
  """A fresh client order id: a decimal integer below `2^63` (ADR 0029)."""
  return str(secrets.randbelow(CLIENT_ORDER_IDS))


def listed(m: MarketInfo) -> bool:
  """Whether a market trades: enabled off-chain (`active`) and unlocked on-chain.

  Mainnet's deprecated `DOGE/USDC` (13) is inactive; testnet's stale markets (a
  deprecated DOGE, LINK, LTC, ...) are locked, with a funding time frozen in the past.
  """
  return m['active'] and m['config']['unlocked']


def market_index(market_id: str) -> int:
  """An SDK market id as the venue's numeric `market_id`.

  Raises:
    ValueError: The id is not a decimal integer.
  """
  try:
    return int(market_id)
  except ValueError:
    raise ValueError(f'RISEx market ids are integers: {market_id!r}') from None


@dataclass(frozen=True, kw_only=True)
class Shared(SDK):
  """Own one client for one account; cache markets and share reads and streams."""

  client: RISEx
  network: Network = 'mainnet'
  """The deployment this client is connected to."""
  account_id: str | None = None
  """Root SDK account key; `None` when built directly, reporting `venue_id` instead."""
  address: str | None = None
  """The account every account read is for: the keys' account, or a configured
  address alone (RISEx's account reads are public)."""
  validate: bool = True
  """Whether responses are validated, for the clients streams open on their own."""
  markets: dict[int, MarketInfo] = field(default_factory=dict[int, MarketInfo])
  """Every market of the deployment, unlisted ones included, by `market_id`."""
  lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  books: dict[int, Subscription[Book]] = field(
    default_factory=dict[int, Subscription[Book]]
  )
  """One shared upstream book per market, each on its own connection."""
  fills: dict[str, Subscription[FillsMessage]] = field(
    default_factory=dict[str, Subscription[FillsMessage]]
  )
  """The account's one fills upstream (every market), under its address, once opened."""
  reads: SharedReads = field(default_factory=SharedReads)
  """Account reads shared between markets and concurrent callers."""

  @classmethod
  def new(
    cls,
    *,
    network: Network = 'mainnet',
    account_key: str | None = None,
    signer_key: str | None = None,
    address: str | None = None,
    validate: bool = True,
    account_id: str | None = None,
  ):
    """Build a client for one account from explicit credentials; the environment is
    never read.

    Args:
      network: RISEx deployment.
      account_key: The account wallet's private key: logs in for JWT reads (`fees`).
      signer_key: A registered signer's private key: signs orders and cancels, logs in,
        and authenticates the fills stream.
      address: The account's address. Optional with an account key (checked against
        it); required with a signer key alone. Without keys, an address alone serves
        every public account read.
      validate: Validate responses.
      account_id: Root SDK account key, the first segment of every market ID;
        defaults to the venue ID.
    """
    if account_key or signer_key:
      client = RISEx.new(
        network=network,
        account_key=account_key,
        signer_key=signer_key,
        account=address,
        validate=validate,
      )
      credentials = client.credentials
      if credentials is None:
        raise AuthError('typed-risex resolved no credentials for the keys')
      address = credentials.account
    else:
      client = RISEx.new(network=network, public=True, validate=validate)
    return cls(
      client=client,
      network=network,
      account_id=account_id,
      address=address or None,
      validate=validate,
    )

  @property
  def venue_id(self) -> VenueId:
    """The deployment's venue ID."""
    return network_venue_id(self.network)

  @cached_property
  def client_resource(self) -> ManagedResource[object]:
    """Own the client with the SDK's exception translation on entry and exit."""
    return ManagedResource(
      resource=self.client, wrap_enter=wrap_exceptions, wrap_exit=wrap_exceptions
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """The client root owns every transport."""
    yield self.client_resource

  @SDK.method
  @wrap_exceptions
  async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Translate one request, or one page: the unit SDK retries apply to."""
    return await fn()

  def public_client(self) -> RISEx:
    """A fresh credential-free client of the same deployment, for a stream that needs a
    connection of its own (a client holds one subscription per channel)."""
    return RISEx.new(network=self.network, public=True, validate=self.validate)

  def require_account(self) -> str:
    """The account account reads are for, before any request.

    Raises:
      AuthError: Neither a key nor an address was configured.
    """
    if self.address is None:
      raise AuthError(
        'RISEx account reads need the account: configure its `address` (or a key)'
      )
    return self.address

  def require_keys(self):
    """Check the client can log in, before a JWT read.

    Raises:
      AuthError: The client has no key (public, or an address alone).
    """
    if self.client.credentials is None:
      raise AuthError(
        'This RISEx read needs a login: configure the `signer_key` or `account_key` '
        '(an address alone only reads public account data)'
      )

  def require_signer(self):
    """Check the client can sign permits, before an order, a cancel or the fills stream.

    Raises:
      AuthError: The client has no signer key.
    """
    credentials = self.client.credentials
    if credentials is None or credentials.signer_key is None:
      raise AuthError(
        'RISEx orders, cancels and the fills stream are signed by a registered signer: '
        'configure the `signer_key`'
      )

  async def load_markets(self, *, refetch: bool = False) -> Mapping[int, MarketInfo]:
    """Every market of the deployment, from one request, cached until `refetch`.

    `refetch` bypasses the venue's own 5-minute cache too (`force_refresh`).
    """
    async with self.lock:
      if refetch or not self.markets:
        result = await self.call(lambda: self.client.markets.all(refetch or None))
        self.markets.clear()
        self.markets.update((m['market_id'], m) for m in result['markets'])
    return self.markets

  async def market(self, market_id: int, *, refetch: bool = False) -> MarketInfo:
    """One market's cached row, unlisted ones included.

    Raises:
      ValueError: The deployment has no market of that id.
    """
    markets = await self.load_markets(refetch=refetch)
    row = markets.get(market_id)
    if row is None:
      raise ValueError(f'Unknown RISEx market: {market_id!r}')
    return row

  async def fresh(self, market_id: int) -> MarketInfo:
    """One market's row with live prices, past the venue's 5-minute cache.

    Raises:
      ValueError: The deployment has no market of that id.
    """
    await self.market(market_id)
    result = await self.call(
      lambda: self.client.markets.all(True, market_ids=[market_id])
    )
    for row in result['markets']:
      if row['market_id'] == market_id:
        return row
    raise ValueError(f'Unknown RISEx market: {market_id!r}')
