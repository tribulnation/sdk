"""Shared client ownership, instrument metadata, account reads and native identities."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from functools import cached_property
from typing_extensions import (
  AsyncContextManager,
  AsyncIterable,
  AsyncIterator,
  Awaitable,
  Callable,
  Iterable,
  Literal,
  TypeVar,
)

from typed_kucoin.account import Account
from typed_kucoin.account.futures_account import FuturesAccountOverview
from typed_kucoin.account.spot_accounts import SpotAccountEntry
from typed_kucoin.schemas import (
  FuturesContract,
  FuturesOrderEvent,
  PositionDetail,
  SpotSymbol,
)
from typed_kucoin.schemas import UtaExecutionEvent, UtaPosition
from typed_kucoin.streams.spot_margin_private.order_v2 import OrderChangeEvent
from typed_kucoin.uta.account.balance import UtaAccountBalance
from typed_kucoin.uta.account.overview import UtaAccountOverview
from tribulnation.sdk import SDK
from tribulnation.sdk.core import (
  OverflowPolicy,
  SharedReads,
  SkippingView,
  Subscription,
)
from tribulnation.sdk.market import Book
from ..core import Mixin

U = TypeVar('U')
Scope = Literal['spot', 'perp']
"""The two product lines: spot and linear perpetual futures."""
Mode = Literal['classic', 'unified']
"""The account's mode: Classic (separate spot and futures accounts and APIs) or Unified
Trading Account (one account and one API for every product line)."""
Feed = Literal['spot', 'perp', 'unified']
"""A private order-event upstream: one per Classic product line, one for UTA."""
OrderEvent = OrderChangeEvent | FuturesOrderEvent | UtaExecutionEvent
"""A private push of a fill or order change: Classic spot or futures order lifecycle, or
a UTA execution."""
SPOT_ACCOUNTS = 'spot_accounts'
"""`SharedReads` key of the spot `trade` account balances."""
POSITIONS = 'positions'
"""`SharedReads` key of the all-symbol futures position list."""
UTA_BALANCE = 'uta_balance'
"""`SharedReads` key of the UTA per-currency assets."""
UTA_OVERVIEW = 'uta_overview'
"""`SharedReads` key of the UTA margin overview."""
UTA_POSITIONS = 'uta_positions'
"""`SharedReads` key of the UTA open futures positions."""
POSITIONS_PAGE = 200
"""Most rows one UTA position or open-order page holds."""


def linear_perpetual(row: FuturesContract) -> bool:
  """Select perpetuals whose positive multiplier converts lots to base units."""
  return (
    row['expireDate'] is None
    and not row['isInverse']
    and row['settleCurrency'] == row['quoteCurrency']
    and row['multiplier'] > 0
  )


@dataclass(frozen=True, kw_only=True)
class Shared(Mixin):
  """Own one client and cache instrument definitions, account reads and shared feeds."""

  account_id: str | None = None
  """Root SDK account key; `None` when built directly, reporting `venue_id` instead."""
  spot: dict[str, SpotSymbol] = field(default_factory=dict[str, SpotSymbol])
  perp: dict[str, FuturesContract] = field(default_factory=dict[str, FuturesContract])
  lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  books: dict[tuple[str, str], Subscription[Book]] = field(
    default_factory=dict[tuple[str, str], Subscription[Book]]
  )
  orders: dict[Feed, Subscription[OrderEvent]] = field(
    default_factory=dict[Feed, Subscription[OrderEvent]]
  )
  """One private order-event upstream per feed, fanned out to every market."""
  mode: Mode | None = None
  """The account mode this client was built for; `None` detects it on first use."""
  detected: dict[Literal['mode'], Mode] = field(
    default_factory=dict[Literal['mode'], Mode]
  )
  """The detected account mode, once read."""
  reads: SharedReads = field(default_factory=SharedReads)
  """Account-wide reads shared between markets and concurrent callers (ADR 0054)."""
  leverages: dict[str, int] = field(default_factory=dict[str, int])
  """Last cross leverage read or set per perpetual, sent with each order."""

  @cached_property
  def futures_api(self) -> Account:
    """Account endpoints that live on the futures host: the futures account overview and
    futures fee rates. typed-kucoin roots every Account endpoint at the spot host, where
    these two do not exist, so they are rebound to the futures connection here."""
    return Account(client=self.client.futures_rest_client)

  @property
  def private(self) -> bool:
    """Whether the client carries credentials."""
    return self.client.default_client.credentials is not None

  async def account_mode(self) -> Mode:
    """The account's mode: the one passed to `new`, else detected once and cached.

    A public client is Classic without a request; it reads only public data, which is
    the same in both modes. Otherwise `GET /api/ua/v2/account/mode` (weight 30, any
    key) answers `CLASSIC` or `UNIFIED` for the key's own account.
    """
    if self.mode is not None:
      return self.mode
    elif not self.private:
      return 'classic'
    else:
      async with self.lock:
        if 'mode' not in self.detected:
          row = await self.call(self.client.uta.account.mode)
          self.detected['mode'] = (
            'unified' if row['selfAccountMode'] == 'UNIFIED' else 'classic'
          )
      return self.detected['mode']

  async def spot_symbols(self, *, refetch: bool = False) -> dict[str, SpotSymbol]:
    """Cache the venue's complete spot definitions, including disabled pairs."""
    async with self.lock:
      if refetch or not self.spot:
        rows = await self.call(self.client.spot.all_symbols)
        self.spot.clear()
        self.spot.update((row['symbol'], row) for row in rows)
    return self.spot

  async def perp_symbols(self, *, refetch: bool = False) -> dict[str, FuturesContract]:
    """Cache active linear perpetuals, excluding inverse and dated contracts."""
    async with self.lock:
      if refetch or not self.perp:
        rows = await self.call(self.client.futures.all_symbols)
        self.perp.clear()
        self.perp.update(
          (row['symbol'], row)
          for row in rows
          if linear_perpetual(row) and row['status'] == 'Open'
        )
    return self.perp

  async def spot_accounts(self, *, ttl: timedelta | None) -> list[SpotAccountEntry]:
    """The spot `trade` account's balances, the only account HF orders spend from."""

    async def fetch() -> list[SpotAccountEntry]:
      """One signed request for every currency."""
      return await self.call(lambda: self.client.account.spot_accounts(type='trade'))

    return await self.reads.read(SPOT_ACCOUNTS, fetch, ttl=ttl)

  async def positions(self, *, ttl: timedelta | None) -> list[PositionDetail]:
    """Every futures position row of the account, one request for all symbols."""

    async def fetch() -> list[PositionDetail]:
      """One signed request for every symbol."""
      return await self.call(self.client.futures.positions.get_position_list)

    return await self.reads.read(POSITIONS, fetch, ttl=ttl)

  async def futures_account(
    self, currency: str, *, ttl: timedelta | None
  ) -> FuturesAccountOverview:
    """The futures account overview of one settlement currency."""

    async def fetch() -> FuturesAccountOverview:
      """One signed request for the currency's pool."""
      return await self.call(lambda: self.futures_api.futures_account(currency))

    return await self.reads.read(('futures_account', currency), fetch, ttl=ttl)

  async def uta_balance(self, *, ttl: timedelta | None) -> UtaAccountBalance:
    """The UTA per-currency assets, one request for every currency."""

    async def fetch() -> UtaAccountBalance:
      """One signed request."""
      return await self.call(self.client.uta.account.balance)

    return await self.reads.read(UTA_BALANCE, fetch, ttl=ttl)

  async def uta_overview(self, *, ttl: timedelta | None) -> UtaAccountOverview:
    """The UTA account-level margin summary, in USD."""

    async def fetch() -> UtaAccountOverview:
      """One signed request."""
      return await self.call(self.client.uta.account.overview)

    return await self.reads.read(UTA_OVERVIEW, fetch, ttl=ttl)

  async def uta_positions(self, *, ttl: timedelta | None) -> list[UtaPosition]:
    """Every open UTA futures position, every page."""

    async def fetch() -> list[UtaPosition]:
      """Page until a short page."""
      rows: list[UtaPosition] = []
      page = 1
      while True:
        batch = await self.call(
          lambda: self.client.uta.positions.open_positions(
            page_number=page, page_size=POSITIONS_PAGE
          )
        )
        rows.extend(batch)
        if len(batch) < POSITIONS_PAGE:
          return rows
        page += 1

    return await self.reads.read(UTA_POSITIONS, fetch, ttl=ttl)

  @asynccontextmanager
  async def stream(
    self,
    scope: Feed,
    connect: Callable[[], Awaitable[Subscription.Context[OrderEvent]]],
    *,
    select: Callable[[OrderEvent], U | None],
    queue_size: int,
    overflow: OverflowPolicy,
  ) -> AsyncIterator[AsyncIterable[U]]:
    """Subscribe to the product line's shared order-event upstream, mapping per market.

    The upstream opens with its first subscriber and closes with its last. When the
    connection drops every subscriber fails with `NetworkError`; subscribing again
    reconnects with a fresh bullet token and resubscribes.
    """
    if scope not in self.orders:
      self.orders[scope] = Subscription(connect)
    async with self.orders[scope].subscribe(
      queue_size=queue_size, overflow=overflow
    ) as upstream:

      async def selected() -> AsyncIterator[U]:
        """Yield this subscriber's view of each shared event."""
        async for item in upstream:
          if (value := select(item)) is not None:
            yield value

      yield SkippingView(selected(), upstream)


@dataclass(frozen=True, kw_only=True)
class Public(SDK):
  """Share one resource owner across venue, exchange and market objects."""

  shared: Shared

  @property
  def venue_id(self) -> Literal['kucoin']:
    """The Catalogue platform ID."""
    return 'kucoin'

  @property
  def account_id(self) -> str:
    """Root SDK account key this object was opened under, else `venue_id`."""
    return self.shared.account_id or self.venue_id

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """Enter the shared owner through the SDK lifecycle."""
    yield self.shared
