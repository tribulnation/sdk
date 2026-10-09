"""Lighter client ownership, request middleware, venue constants and cached metadata."""

from functools import cached_property
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
import asyncio
import time

from typing_extensions import (
  AsyncContextManager,
  Awaitable,
  Callable,
  Iterable,
  Literal,
  Sequence,
  TypeVar,
)
from typed_lighter import Lighter
from typed_lighter.api.account.get import DetailedAccount
from typed_lighter.api.markets.order_book_details import (
  PerpsOrderBookDetail,
  SpotOrderBookDetail,
)
from typed_lighter.core.networks import Network
from typed_lighter.scaling import Scaler
from tribulnation.sdk import SDK
from tribulnation.sdk.core import (
  AuthError,
  ManagedResource,
  Subscription,
  exception_wrapper,
)
from tribulnation.sdk.market import Book, Trade

T = TypeVar('T')

FEE_TICK = Decimal('1e-6')
"""Fee ticks (`account/limits`, trades) are parts per million of notional: tier `plus`
reports 50/50 (0.5 bps), `premium` 40/280 (0.0040%/0.0280%)."""
USDC = 3
"""USDC's asset id: perpetuals settle margin, PnL, fees and funding in it."""
FUNDING_INTERVAL = timedelta(hours=1)
"""Lighter settles funding every hour, on the hour."""
MAX_CLIENT_INDEX = 2**48
"""Client order indexes are uint48."""
MASTER = 0
"""`account_type` of an L1 address's master account (sub-accounts are `1`, pools `2`-`4`)."""
DepthSource = Literal['order_book', 'bbo']
"""Which Lighter WebSocket channel backs `depth_stream`; see `market.common.Settings`."""


@dataclass
class ClientIndexes:
  """Allocate strictly increasing client order indexes: microseconds since the epoch,
  bumped past the last one so concurrent placements never collide."""

  last: int = 0

  def next(self) -> int:
    """A fresh client order index."""
    self.last = max(time.time_ns() // 1000, self.last + 1)
    return self.last % MAX_CLIENT_INDEX


def network_venue_id(network: Network) -> Literal['lighter', 'lighter_testnet']:
  """The venue ID of a deployment: testnet deployments report `'lighter_testnet'`."""
  return 'lighter_testnet' if network.endswith('testnet') else 'lighter'


@dataclass(frozen=True, kw_only=True)
class Shared(SDK):
  """Own one client; cache market details, scalers and shared stream fan-outs."""

  client: Lighter
  venue_id: Literal['lighter', 'lighter_testnet'] = 'lighter'
  """The deployment this client is connected to, as a venue ID."""
  account_id: str | None = None
  """Root SDK account key; `None` when built directly, reporting `venue_id` instead."""
  perps: dict[int, PerpsOrderBookDetail] = field(
    default_factory=dict[int, PerpsOrderBookDetail]
  )
  spots: dict[int, SpotOrderBookDetail] = field(
    default_factory=dict[int, SpotOrderBookDetail]
  )
  scalers: dict[int, Scaler] = field(default_factory=dict[int, Scaler])
  lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  books: dict[tuple[int, DepthSource], Subscription[Book]] = field(
    default_factory=dict[tuple[int, DepthSource], Subscription[Book]]
  )
  """One shared upstream per market and depth source."""
  fills: dict[int, Subscription[Trade]] = field(
    default_factory=dict[int, Subscription[Trade]]
  )
  client_indexes: ClientIndexes = field(default_factory=ClientIndexes)
  leverages: dict[int, Decimal] = field(default_factory=dict[int, Decimal])
  """The account's leverage per perpetual market, filled by `leverage()`."""
  public_index: int | None = None
  """Account for public account reads when the client has no credentials."""
  address: str | None = None
  """L1 address whose master account public account reads use, when neither the
  credentials nor `public_index` name an account."""
  masters: dict[str, int] = field(default_factory=dict[str, int])
  """Master account index per resolved L1 address."""

  @classmethod
  def new(
    cls,
    account_index: int | None = None,
    api_key_index: int | None = None,
    api_private_key: str | None = None,
    *,
    auth_token: str | None = None,
    address: str | None = None,
    network: Network = 'mainnet',
    public: bool = False,
    validate: bool = True,
    account_id: str | None = None,
  ):
    """Build a client from explicit credentials, or the client's `LIGHTER_*` defaults.

    Args:
      account_index: Account the credentials belong to; in public mode, the account
        public account reads use.
      api_key_index: Slot of the API key.
      api_private_key: Private key of the API key.
      auth_token: Read-only auth token, for private reads without an API key.
      address: L1 address whose master account public account reads use when no
        account index is known.
      network: Lighter deployment.
      public: Skip credentials: public market data, plus public account reads of
        `account_index` or `address`.
      validate: Validate responses.
      account_id: Root SDK account key, the first segment of every market ID;
        defaults to the venue ID.
    """
    return cls(
      venue_id=network_venue_id(network),
      account_id=account_id,
      public_index=account_index if public else None,
      address=address,
      client=Lighter.new(
        network=network,
        account_index=account_index,
        api_key_index=api_key_index,
        api_private_key=api_private_key,
        auth_token=auth_token,
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
  def private_index(self) -> int:
    """The credentials' account, for token-gated reads (an API key or auth token).

    Raises:
      AuthError: The client has neither.
    """
    index = self.client.account_index
    if index is None:
      raise AuthError(
        'This Lighter read needs an API key or a read-only auth token (`auth_token`)'
      )
    return index

  def require_api_key(self):
    """Check the client can sign transactions, before trading.

    Raises:
      AuthError: The client has no API key (none, or only a read-only auth token).
    """
    if self.client.account_signer is None:
      raise AuthError(
        'Lighter trading needs an API key (`api_key_index` and `api_private_key`); '
        'an auth token only allows reads'
      )

  async def account_index(self) -> int:
    """The account public account reads use: the credentials' account, else the
    configured `account_index`, else the master account of the configured `address`
    (`account_type` 0), resolved once.

    Raises:
      AuthError: No credentials, account index or address is configured.
      ValueError: The address has no master account.
    """
    if (index := self.client.account_index) is not None:
      return index
    if self.public_index is not None:
      return self.public_index
    address = self.address
    if address is None:
      raise AuthError(
        'Account-scoped Lighter data needs an account: configure an API key, an auth '
        'token, an `account_index` or an `address`'
      )
    if address not in self.masters:
      response = await self.call(
        lambda: self.client.api.account.get({'by': 'l1_address', 'value': address})
      )
      self.masters[address] = master_index(response['accounts'], address)
    return self.masters[address]

  async def load_details(self, *, refetch: bool = False):
    """Cache every market's details, perpetual and spot, from one request."""
    async with self.lock:
      if refetch or not self.perps:
        details = await self.call(self.client.api.markets.order_book_details)
        self.perps.clear()
        self.perps.update(
          (d['market_id'], d) for d in details['order_book_details'] or []
        )
        self.spots.clear()
        self.spots.update(
          (d['market_id'], d) for d in details['spot_order_book_details'] or []
        )

  async def perp(
    self, market_id: int, *, refetch: bool = False
  ) -> PerpsOrderBookDetail:
    """One perpetual market's details."""
    await self.load_details(refetch=refetch)
    if market_id not in self.perps:
      raise ValueError(f'Unknown Lighter perpetual market: {market_id}')
    return self.perps[market_id]

  async def spot(self, market_id: int, *, refetch: bool = False) -> SpotOrderBookDetail:
    """One spot market's details."""
    await self.load_details(refetch=refetch)
    if market_id not in self.spots:
      raise ValueError(f'Unknown Lighter spot market: {market_id}')
    return self.spots[market_id]

  async def scaler(self, market_id: int) -> Scaler:
    """The market's price and size scales for signing."""
    if market_id not in self.scalers:
      await self.load_details()
      detail = self.perps.get(market_id) or self.spots.get(market_id)
      if detail is None:
        raise ValueError(f'Unknown Lighter market: {market_id}')
      self.scalers[market_id] = Scaler.from_details(detail)
    return self.scalers[market_id]

  async def account(self) -> DetailedAccount:
    """The configured account's positions, balances and margin figures."""
    index = await self.account_index()
    accounts = await self.call(
      lambda: self.client.api.account.get({'by': 'index', 'value': index})
    )
    return accounts['accounts'][0]


def master_index(accounts: Sequence[DetailedAccount], address: str) -> int:
  """The master account's index among an L1 address's accounts.

  Raises:
    ValueError: None of them is a master account (an unknown address).
  """
  for a in accounts:
    if a['account_type'] == MASTER:
      return a['index']
  raise ValueError(f'Lighter address {address} has no master account')


def parse_market_id(market_id: str) -> int:
  """The venue's numeric market id from its SDK string form."""
  try:
    return int(market_id)
  except ValueError:
    raise ValueError(f'Lighter market ids are numeric: {market_id!r}') from None


def percent(value: Decimal) -> Decimal:
  """A venue percentage as a fraction."""
  return value / 100
