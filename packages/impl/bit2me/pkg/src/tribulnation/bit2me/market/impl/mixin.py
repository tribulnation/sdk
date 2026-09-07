"""Shared state and mixins behind Bit2Me's Trading Spot market surface.

Bit2Me has no derivatives product -- `typed_bit2me` has no futures, perpetual or
funding surface at all -- so `spot` is the venue's only exchange and there is no
`PerpMarket` here.
"""

from typing_extensions import (
  Any,
  AsyncContextManager,
  AsyncIterable,
  AsyncIterator,
  Awaitable,
  Callable,
  Iterable,
  TypedDict,
  TypeVar,
)
from dataclasses import dataclass, field
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timedelta, timezone
import asyncio

from tribulnation.sdk.core import OverflowPolicy, Subscription
from tribulnation.sdk.market import Book
from tribulnation.bit2me.core import Calls, wrap_exceptions

from typed_bit2me import Bit2Me
from typed_bit2me.schemas import WalletResponse
from typed_bit2me.trading_ws import TradingWs
from typed_bit2me.trading_ws.my_trades import MyTradeUpdate
from typed_bit2me.v1.trading.markets import Entry as MarketInfo

from .depth import parse_book

T = TypeVar('T')

BALANCE_TTL = timedelta(seconds=1)
"""How long a fetched balance list is reused before another call is made.

`v1/trading/wallet/balance` rate-limits far tighter than the market-data endpoints:
the sixth call in quick succession answers `429`, with or without a `symbols` filter,
while `v1/trading/market-config` takes a dozen in a row. `position`, `collateral` and
`available_notional` each need the list, so a caller sweeping a handful of markets
trips the limit within one logical operation unless those calls coalesce.
"""


class Meta(TypedDict):
  """What a `SpotMarket` is constructed around."""

  info: MarketInfo


def context(
  stream: AsyncIterable[T], unsubscribe: Callable[[], Awaitable[Any]]
) -> Subscription.Context[T]:
  """Wrap a typed-client stream as the `(iterator, unsubscribe)` pair a
  `Subscription` fans out from.

  Iteration is wrapped too, not just the subscribe call: a socket that drops
  mid-stream raises from the `async for`, and that has to reach subscribers as a
  `tribulnation.sdk.core` error like every other failure.
  """

  @wrap_exceptions
  async def iterate() -> AsyncIterator[T]:
    async for item in stream:
      yield item

  return Subscription.Context(iterate(), unsubscribe)


@asynccontextmanager
async def closing_ws(shared: 'Shared'):
  """Close the Trading Spot socket at exit, if a subscription ever opened it.

  Held by reference and checked only on exit, so a socket opened lazily inside the
  block is still closed -- which is why `Shared` cannot simply yield `trading_ws`
  from `resources()`. Entering it eagerly would also cost a signed token mint and a
  WebSocket handshake for a client that may only ever read REST.
  """
  try:
    yield shared
  finally:
    if (stack := shared.ws_stack) is not None:
      shared.ws_stack = None
      await stack.aclose()


@dataclass(kw_only=True)
class Shared(Calls):
  """State shared by every market of one Bit2Me client."""

  client: Bit2Me
  balance_ttl: timedelta = BALANCE_TTL
  markets: dict[str, MarketInfo] | None = None
  balances: dict[str, WalletResponse] | None = None
  balances_at: datetime | None = None
  ws_stack: AsyncExitStack | None = None
  depth_subscriptions: dict[str, Subscription[Book]] = field(
    default_factory=dict[str, Subscription[Book]]
  )
  trade_subscriptions: dict[str, Subscription[MyTradeUpdate]] = field(
    default_factory=dict[str, Subscription[MyTradeUpdate]]
  )
  markets_lock: asyncio.Lock = field(
    default_factory=asyncio.Lock, init=False, repr=False
  )
  balances_lock: asyncio.Lock = field(
    default_factory=asyncio.Lock, init=False, repr=False
  )
  ws_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    api_secret: str | None = None,
    *,
    public: bool = False,
    validate: bool = True,
  ):
    """Build the shared state around a fresh Bit2Me client."""
    return cls(
      client=Bit2Me.new(
        api_key=api_key, api_secret=api_secret, public=public, validate=validate
      )
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield self.client
    yield closing_ws(self)

  async def load_markets(self, *, refetch: bool = False) -> dict[str, MarketInfo]:
    """Fetch and memoise the whole market catalogue.

    Args:
      refetch: Refetch even when the catalogue is already cached.
    """
    if not refetch and self.markets is not None:
      return self.markets
    async with self.markets_lock:
      if not refetch and self.markets is not None:
        return self.markets
      entries = await self.call_bit2me(self.client.v1.trading.markets)
      self.markets = {
        symbol: entry for entry in entries if (symbol := entry.get('symbol'))
      }
      return self.markets

  async def load_balances(self, *, refetch: bool = False) -> dict[str, WalletResponse]:
    """Fetch the Trading Spot balance of every asset, keyed by currency.

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
        entries = await self.call_bit2me(self.client.v1.trading.balance)
        self.balances = {entry['currency']: entry for entry in entries}
        self.balances_at = now
      return self.balances

  async def trading_ws(self) -> TradingWs:
    """Connect and authenticate the shared Trading Spot socket, once.

    One multiplexed connection carries every channel, and entering it is a separate
    step from subscribing: it connects and, when credentials are present, mints and
    sends a WS token. Doing that per subscription would re-authenticate a socket
    that is already logged in.
    """
    async with self.ws_lock:
      if self.ws_stack is None:
        stack = AsyncExitStack()
        await stack.enter_async_context(self.client.trading_ws)
        self.ws_stack = stack
    return self.client.trading_ws

  def depth_subscription(self, symbol: str) -> Subscription[Book]:
    """The shared order-book subscription for one market, created on first use."""
    if symbol not in self.depth_subscriptions:

      @wrap_exceptions
      async def subscribe() -> Subscription.Context[Book]:
        ws = await self.trading_ws()
        stream = await ws.order_book(symbol)
        return context(stream.map(parse_book), stream.unsubscribe)

      self.depth_subscriptions[symbol] = Subscription(subscribe)
    return self.depth_subscriptions[symbol]

  def trade_subscription(self, symbol: str) -> Subscription[MyTradeUpdate]:
    """The shared own-trades subscription for one market, created on first use."""
    if symbol not in self.trade_subscriptions:

      @wrap_exceptions
      async def subscribe() -> Subscription.Context[MyTradeUpdate]:
        ws = await self.trading_ws()
        stream = await ws.my_trades(symbol)
        return context(stream, stream.unsubscribe)

      self.trade_subscriptions[symbol] = Subscription(subscribe)
    return self.trade_subscriptions[symbol]


@dataclass(frozen=True, kw_only=True)
class SharedMixin(Calls):
  """Base for every Bit2Me market object, holding the state they share."""

  shared: Shared

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    api_secret: str | None = None,
    *,
    public: bool = False,
    validate: bool = True,
  ):
    """Build a market surface around a fresh Bit2Me client.

    Args:
      api_key: Bit2Me API key; read from `BIT2ME_API_KEY` when omitted.
      api_secret: Bit2Me API secret; read from `BIT2ME_SECRET_KEY` when omitted.
      public: Build a public-only client. Market data works without credentials;
        orders, balances and the private channels do not.
      validate: Validate responses.
    """
    return cls(shared=Shared.new(api_key, api_secret, public=public, validate=validate))

  @property
  def client(self) -> Bit2Me:
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
  def info(self) -> MarketInfo:
    return self.meta['info']

  @property
  def symbol(self) -> str:
    symbol = self.info.get('symbol')
    if symbol is None:
      raise ValueError('Bit2Me market metadata is missing its symbol')
    return symbol

  @property
  def base(self) -> str:
    return self.symbol.partition('/')[0]

  @property
  def quote(self) -> str:
    return self.symbol.partition('/')[2]

  def subscribe_depth(
    self, *, queue_size: int = 1, overflow: OverflowPolicy = 'latest'
  ):
    """Subscribe to this market's shared order-book stream."""
    return self.shared.depth_subscription(self.symbol).subscribe(
      queue_size=queue_size, overflow=overflow
    )

  def subscribe_trades(
    self, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
  ):
    """Subscribe to this market's shared own-trades stream."""
    return self.shared.trade_subscription(self.symbol).subscribe(
      queue_size=queue_size, overflow=overflow
    )
