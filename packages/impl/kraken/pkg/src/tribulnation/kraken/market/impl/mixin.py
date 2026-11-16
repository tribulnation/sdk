"""Shared state for Kraken Spot and public linear perpetual markets.

Spot market IDs use REST altnames; Futures market IDs retain instrument symbols.
The shared client owns transports while each request crosses the retry seam.
"""

from functools import cached_property

from typing_extensions import (
  Any,
  AsyncContextManager,
  AsyncIterable,
  AsyncIterator,
  Awaitable,
  Callable,
  Iterable,
  Literal,
  TypedDict,
  TypeVar,
)
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import asyncio

from tribulnation.sdk.core import ManagedResource, OverflowPolicy, Subscription
from tribulnation.sdk.market import Book
from tribulnation.kraken.core import Calls, wrap_exceptions

from typed_kraken import Kraken
from typed_kraken.futures.instruments import FuturesInstrument
from typed_kraken.futures_trading.http import DEMO_FUTURES_URL, FUTURES_URL
from .perp_data import select_perps
from typed_kraken.spot.account.balance_ex import ExtendedBalance
from typed_kraken.spot.market_data.asset_pairs import AssetPair
from typed_kraken.streams.private.executions import ExecutionTradeEvent

from .depth import BookDepth, fold_books
from .futures_state import FuturesState
from .pairs import Meta, PairInfo, join_pairs
from .streaming import context

T = TypeVar('T')

KrakenVenue = Literal['kraken', 'kraken_testnet']
"""`kraken` is the live venue; `kraken_testnet` is the Futures demo environment, which
has perpetuals only."""

BALANCE_TTL = timedelta(seconds=1)
"""How long a fetched balance list is reused before another call is made.

Kraken meters private REST calls with a per-account counter that decays at a fraction
of a point per second, and `position`, `collateral` and `available_notional` each need
the same `BalanceEx` answer, so a caller sweeping a handful of markets coalesces those
calls rather than spending three counter points per market.
"""


@dataclass(kw_only=True)
class Shared(Calls):
  """State shared by every market of one Kraken client.

  Spot and the public perpetual reads go through `client`; the Futures account, orders
  and feeds through `perp`, which holds the separate Futures API key.
  """

  client: Kraken
  perp: FuturesState = field(default_factory=FuturesState.new)
  venue: KrakenVenue = 'kraken'
  account_id: str | None = None
  """Root SDK account key; `None` when built directly, reporting `'kraken'` instead."""
  balance_ttl: timedelta = BALANCE_TTL
  pairs: dict[str, PairInfo] | None = None
  perp_instruments: dict[str, FuturesInstrument] | None = None
  fee_asset: str | None = None
  perp_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
  balances: dict[str, ExtendedBalance] | None = None
  balances_at: datetime | None = None
  depth_subscriptions: dict[tuple[str, BookDepth], Subscription[Book]] = field(
    default_factory=dict[tuple[str, BookDepth], Subscription[Book]]
  )
  executions: Subscription[ExecutionTradeEvent] | None = None
  pairs_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
  balances_lock: asyncio.Lock = field(
    default_factory=asyncio.Lock, init=False, repr=False
  )

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    private_key: str | None = None,
    *,
    futures_api_key: str | None = None,
    futures_private_key: str | None = None,
    venue: KrakenVenue = 'kraken',
    margin_schedule: str | None = None,
    public: bool = False,
    validate: bool = True,
    account_id: str | None = None,
  ):
    """Build the shared state around fresh Spot and Futures clients.

    Args:
      api_key: Spot API key; read from `KRAKEN_API_KEY` when omitted.
      private_key: Spot API secret; read from `KRAKEN_PRIVATE_KEY` when omitted.
      futures_api_key: Futures API key. Without a Futures key pair, the perpetuals
        serve public data only.
      futures_private_key: Futures API secret.
      venue: `kraken`, or `kraken_testnet` for the Futures demo environment.
      margin_schedule: See `Shared.margin_schedule`.
      public: Build the Spot client without credentials.
      validate: Validate responses.
      account_id: Root SDK account key.
    """
    demo = venue == 'kraken_testnet'
    return cls(
      client=Kraken.new(
        api_key=api_key,
        private_key=private_key,
        public=public,
        validate=validate,
        futures_url=DEMO_FUTURES_URL if demo else FUTURES_URL,
      ),
      perp=FuturesState.new(
        futures_api_key,
        futures_private_key,
        environment='demo' if demo else 'live',
        margin_schedule=margin_schedule,
        validate=validate,
      ),
      venue=venue,
      account_id=account_id,
    )

  @cached_property
  def client_resource(self) -> ManagedResource[object]:
    """Own client with the venue's entry and cleanup policies."""
    return ManagedResource(
      resource=self.client,
      wrap_enter=wrap_exceptions,
      wrap_exit=wrap_exceptions,
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield self.client_resource
    yield self.perp.resource

  async def load_pairs(self, *, refetch: bool = False) -> dict[str, PairInfo]:
    """Fetch and memoise the whole pair catalogue, keyed by altname.

    Args:
      refetch: Refetch even when the catalogue is already cached.
    """
    if not refetch and self.pairs is not None:
      return self.pairs
    async with self.pairs_lock:
      if not refetch and self.pairs is not None:
        return self.pairs
      internal, display = await asyncio.gather(
        self.call_kraken(self.client.spot.market_data.asset_pairs),
        self.call_kraken(
          lambda: self.client.spot.market_data.asset_pairs(asset_version=1)
        ),
      )
      self.pairs = join_pairs(internal, display)
      return self.pairs

  async def load_perps(self, *, refetch: bool = False) -> dict[str, FuturesInstrument]:
    """Cache the qualified instrument/ticker join, with explicit refresh support."""
    if not refetch and self.perp_instruments is not None:
      return self.perp_instruments
    async with self.perp_lock:
      if not refetch and self.perp_instruments is not None:
        return self.perp_instruments
      instruments = await self.call_kraken(self.client.futures.instruments)
      tickers = await self.call_kraken(self.client.futures.tickers)
      self.perp_instruments = select_perps(
        instruments['instruments'], tickers['tickers']
      )
      return self.perp_instruments

  async def load_fee_asset(self) -> str:
    """Resolve documented USD Futures fees to Kraken's native internal asset ID."""
    if self.fee_asset is None:
      assets = await self.call_kraken(self.client.spot.market_data.assets)
      matches = [key for key, row in assets.items() if row.get('altname') == 'USD']
      if len(matches) != 1:
        raise ValueError('Kraken Assets must identify exactly one USD fee asset')
      self.fee_asset = matches[0]
    return self.fee_asset

  async def load_balances(self, *, refetch: bool = False) -> dict[str, ExtendedBalance]:
    """Fetch every asset's extended balance, keyed by internal asset id.

    Reuses a result younger than `balance_ttl` rather than refetching -- see that
    constant for the rate limit this exists to stay under.

    Args:
      refetch: Refetch even when a fresh result is cached.
    """
    async with self.balances_lock:
      now = datetime.now(timezone.utc)
      fresh = (
        self.balances is not None
        and self.balances_at is not None
        and now - self.balances_at < self.balance_ttl
      )
      if self.balances is None or refetch or not fresh:
        self.balances = dict(
          await self.call_kraken(self.client.spot.account.balance_ex)
        )
        self.balances_at = now
      return self.balances

  def depth_subscription(self, symbol: str, depth: BookDepth) -> Subscription[Book]:
    """The shared order-book subscription for one symbol and depth, created on
    first use."""
    if (symbol, depth) not in self.depth_subscriptions:

      @wrap_exceptions
      async def subscribe() -> Subscription.Context[Book]:
        stream = await self.client.streams.market_data.book(
          symbol=[symbol], depth=depth
        )
        return context(fold_books(stream), stream.unsubscribe)

      self.depth_subscriptions[(symbol, depth)] = Subscription(subscribe)
    return self.depth_subscriptions[(symbol, depth)]

  def executions_subscription(self) -> Subscription[ExecutionTradeEvent]:
    """The shared own-fills subscription, created on first use.

    `executions` is one account-wide channel carrying both order-status transitions
    and fills; only the fills (`exec_type == 'trade'`) are fanned out, and each
    market filters them by its own symbol.
    """
    if self.executions is None:

      @wrap_exceptions
      async def subscribe() -> Subscription.Context[ExecutionTradeEvent]:
        stream = await self.client.streams.private.executions(snap_trades=False)

        async def fills() -> AsyncIterator[ExecutionTradeEvent]:
          async for message in stream:
            for event in message['data']:
              if event['exec_type'] == 'trade':
                yield event

        return context(fills(), stream.unsubscribe)

      self.executions = Subscription(subscribe)
    return self.executions


@dataclass(frozen=True, kw_only=True)
class SharedMixin(Calls):
  """Base for every Kraken market object, holding the state they share."""

  shared: Shared

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    private_key: str | None = None,
    *,
    futures_api_key: str | None = None,
    futures_private_key: str | None = None,
    venue: KrakenVenue = 'kraken',
    margin_schedule: str | None = None,
    public: bool = False,
    validate: bool = True,
    account_id: str | None = None,
  ):
    """Build a market surface around fresh Spot and Futures clients.

    Args:
      api_key: Kraken Spot API key; read from `KRAKEN_API_KEY` when omitted.
      private_key: Kraken Spot private key; read from `KRAKEN_PRIVATE_KEY` when omitted.
      futures_api_key: Futures API key; without a Futures key pair the perpetuals
        serve public data only.
      futures_private_key: Futures API secret.
      venue: `kraken`, or `kraken_testnet` for the Futures demo environment.
      margin_schedule: `marginSchedules` key whose retail levels set cross-margin
        leverage; `None` reads the instrument's `retailMarginLevels`.
      public: Build a credential-free Spot client. Market data works without
        credentials; balances, orders and the private channels do not.
      validate: Validate responses.
      account_id: Root SDK account key, the first segment of every market ID;
        defaults to the venue ID.
    """
    return cls(
      shared=Shared.new(
        api_key,
        private_key,
        futures_api_key=futures_api_key,
        futures_private_key=futures_private_key,
        venue=venue,
        margin_schedule=margin_schedule,
        public=public,
        validate=validate,
        account_id=account_id,
      )
    )

  @property
  def venue_id(self) -> KrakenVenue:
    """`kraken`, or `kraken_testnet` on the Futures demo environment."""
    return self.shared.venue

  @property
  def account_id(self) -> str:
    """Root SDK account key this object was opened under, else `venue_id`."""
    return self.shared.account_id or self.venue_id

  @property
  def client(self) -> Kraken:
    return self.shared.client

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield from super().resources()
    yield self.shared


@dataclass(frozen=True, kw_only=True)
class ExchangeMixin(SharedMixin):
  """Base for the exchange-level surface."""


@dataclass(frozen=True, kw_only=True)
class MarketMixin(ExchangeMixin):
  """Base for one market's surface."""

  meta: Meta

  @property
  def info(self) -> AssetPair:
    return self.meta['pair']['info']

  @property
  def altname(self) -> str:
    """The REST pair name every `pair=` argument and account row uses (`XBTUSD`)."""
    altname = self.info.get('altname')
    if altname is None:
      raise ValueError('Kraken pair metadata is missing its altname')
    return altname

  @property
  def ws_symbol(self) -> str:
    """The WebSocket v2 symbol (`BTC/USD`)."""
    return self.meta['pair']['symbol']

  @property
  def base(self) -> str:
    """The base asset's internal id (`XXBT`)."""
    return self.info.get('base', '')

  @property
  def quote(self) -> str:
    """The quote asset's internal id (`ZUSD`)."""
    return self.info.get('quote', '')

  def subscribe_depth(
    self,
    depth: BookDepth,
    *,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
  ):
    """Subscribe to this market's shared order-book stream at one of Kraken's depths."""
    return self.shared.depth_subscription(self.ws_symbol, depth).subscribe(
      queue_size=queue_size, overflow=overflow
    )

  def subscribe_fills(
    self, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
  ):
    """Subscribe to the account-wide fills stream."""
    return self.shared.executions_subscription().subscribe(
      queue_size=queue_size, overflow=overflow
    )
