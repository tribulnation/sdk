from typing_extensions import (
  Any,
  AsyncIterable,
  AsyncGenerator,
  Sequence,
  Literal,
  TypedDict,
  Collection,
  Mapping,
  NotRequired,
)
from abc import abstractmethod
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.core import SDK, PaginatedResponse, OverflowPolicy
from tribulnation.sdk.impl.accounts import VenueId
from .types import (
  Book,
  CandleInterval,
  Collateral,
  PerpCollateral,
  NextFunding,
  Order,
  OrderResponse,
  OrderState,
  Position,
  PerpPosition,
  Trade,
  Rules,
  Fees,
  Ticker,
)
from .settings import Settings
from .market import Market, PerpMarket
from .exchange import Exchange, PerpExchange


class ExchangeDescription(TypedDict):
  """One SDK exchange/product family, identified within its owning venue."""

  id: str
  """Opaque stable ID, including the empty string; never a display label."""
  type: Literal['spot', 'perp']
  name: str
  """Nonempty human-readable name within the venue; not an identity or guarantee."""
  url: NotRequired[str]
  """Optional official HTTPS landing page; omitted when no reliable URL is known."""


class TradingVenue(SDK):
  """An abstract multi-exchange venue interface."""

  ExchangeDescription = ExchangeDescription

  @property
  @abstractmethod
  def venue_id(self) -> VenueId:
    """The venue this object trades on, e.g. `'hyperliquid'` or `'dydx_testnet'`;
    never an account key."""

  @property
  @abstractmethod
  def account_id(self) -> str:
    """Key of the account this object was opened under: `'hl'` for
    `MarketSDK({'hl': accounts.Hyperliquid(...)})`. Objects built directly, outside a
    root SDK, default to their `venue_id`."""

  @property
  def id(self) -> str:
    """The account key, `account_id`: the first segment of every ID under this venue."""
    return self.account_id

  @SDK.method
  @abstractmethod
  async def exchange(self, exchange_id: str, /) -> Exchange:
    """Fetch an exchange by ID."""

  @SDK.method
  @abstractmethod
  async def exchanges(self) -> Sequence[ExchangeDescription]:
    """List available exchanges."""

  async def market(self, exchange_market_id: str, /) -> Market:
    """Fetch a market by ID.

    - `exchange_market_id`: `<exchange_id>:<market_id>`
    """
    exchange_id, market_id = exchange_market_id.split(':', 1)
    exchange = await self.exchange(exchange_id)
    return await exchange.market(market_id)

  @SDK.method
  async def depth(
    self, market_id: str, /, *, levels: int | None = None, settings: Settings = {}
  ) -> Book:
    """Fetch the market order book."""
    market = await self.market(market_id)
    return await market.depth(levels=levels, settings=settings)

  @SDK.method
  @asynccontextmanager
  async def depth_stream(
    self,
    market_id: str,
    /,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
    settings: Settings = {},
  ) -> AsyncGenerator[AsyncIterable[Book]]:
    """Subscribe to the market order book.

    See `Market.depth_stream` for `queue_size`/`overflow` (e.g. `overflow='fail'`
    with a larger `queue_size` to capture every book).
    """
    market = await self.market(market_id)
    async with market.depth_stream(
      levels=levels, queue_size=queue_size, overflow=overflow, settings=settings
    ) as stream:
      yield stream

  @SDK.method
  async def tickers(
    self,
    exchange: str,
    *,
    markets: Collection[str] | None = None,
    settings: Settings = {},
  ) -> Mapping[str, Ticker]:
    """Fetch a ticker snapshot for many markets at once.

    Args:
      markets: Market IDs to fetch. `None` fetches every market of the exchange.
      settings: Venue-specific ticker settings.

    Returns:
      A mapping of market ID to its `Ticker`.
    """
    sdk = await self.exchange(exchange)
    return await sdk.tickers(markets=markets, settings=settings)

  @SDK.method
  async def rules(self, market_id: str, /, *, refetch: bool = False) -> Rules:
    """Fetch the market rules.

    - `refetch`: if `True`, fetch the rules even if they are already cached.
    """
    market = await self.market(market_id)
    return await market.rules(refetch=refetch)

  @SDK.method
  async def fees(self, market_id: str, /, *, refetch: bool = False) -> Fees:
    """Fetch the selected market's account rates without a standard-rate fallback."""
    market = await self.market(market_id)
    return await market.fees(refetch=refetch)

  @SDK.method
  @PaginatedResponse.lift
  async def candles(
    self,
    market_id: str,
    /,
    interval: CandleInterval,
    start: datetime,
    end: datetime,
  ):
    """Fetch the market's historical trade candles.

    See `Market.candles` for the paging contract and `Market.CANDLE_INTERVALS`.
    """
    market = await self.market(market_id)
    async for page in market.candles(interval, start, end):
      yield page

  @SDK.method
  async def query_order(self, market_id: str, /, id: str) -> OrderState | None:
    """Fetch the state of the order with the given ID."""
    market = await self.market(market_id)
    return await market.query_order(id)

  @SDK.method
  async def open_orders(self, market_id: str, /) -> Sequence[OrderState]:
    """Fetch your currently open orders."""
    market = await self.market(market_id)
    return await market.open_orders()

  @SDK.method
  @PaginatedResponse.lift
  async def trades_history(self, market_id: str, /, start: datetime, end: datetime):
    """Fetch your trades history."""
    market = await self.market(market_id)
    async for page in market.trades_history(start, end):
      yield page

  @SDK.method
  @asynccontextmanager
  async def trades_stream(
    self,
    market_id: str,
    /,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
    settings: Settings = {},
  ) -> AsyncGenerator[AsyncIterable[Trade]]:
    """Subscribe to your real-time trades.

    See `Market.trades_stream` for `queue_size`/`overflow`/`settings`.
    """
    market = await self.market(market_id)
    async with market.trades_stream(
      queue_size=queue_size, overflow=overflow, settings=settings
    ) as stream:
      yield stream

  @SDK.method
  async def position(self, market_id: str, /) -> Position:
    """Fetch your open position in the market."""
    market = await self.market(market_id)
    return await market.position()

  @SDK.method
  async def collateral(self, id: str, /) -> Collateral:
    """Fetch collateral.

    - 1-segment (`perp`): exchange-level bucket.
    - 2-segment (`perp:BTC-USD`): market-level (mode-aware).
    """
    if ':' in id:
      exchange_id, market_id = id.split(':', 1)
      exchange = await self.exchange(exchange_id)
      return await exchange.collateral(market_id)
    exchange = await self.exchange(id)
    return await exchange.collateral()

  @SDK.method
  async def available_notional(self, market_id: str, /):
    """Fetch the maximum notional position you can open right now.

    - Spot: the free quote-token balance.
    - Perpetuals: the free collateral times the account's `leverage()` on the market.
    """
    market = await self.market(market_id)
    return await market.available_notional()

  @SDK.method
  async def place_order(
    self, market_id: str, /, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Place an order in the market.

    See ``Market.place_order`` for SDK order type semantics and errors.

    Raises:
      OrderRejected: The venue definitively refused the order: nothing rests and
        nothing filled. Other errors may be ambiguous.
    """
    market = await self.market(market_id)
    return await market.place_order(order, settings=settings)

  @SDK.method
  async def cancel_order(
    self, market_id: str, /, id: str, *, settings: Settings = {}
  ) -> Any:
    """Cancel an order in the market."""
    market = await self.market(market_id)
    return await market.cancel_order(id, settings=settings)

  @SDK.method
  async def cancel_orders(
    self, market_id: str, /, ids: Sequence[str], *, settings: Settings = {}
  ) -> Any:
    """Cancel multiple orders in the market."""
    market = await self.market(market_id)
    return await market.cancel_orders(ids, settings=settings)

  @SDK.method
  async def cancel_open_orders(
    self, market_id: str, /, *, settings: Settings = {}
  ) -> Any:
    """Cancel all open orders in the market."""
    market = await self.market(market_id)
    return await market.cancel_open_orders(settings=settings)

  @SDK.method
  async def perp_exchange(self, exchange_id: str, /) -> PerpExchange:
    """Fetch a perpetual exchange by ID."""
    raise NotImplementedError(
      f'Perp exchanges are not supported by this venue [{self.id}].'
    )

  @SDK.method
  async def perp_market(self, exchange_market_id: str, /) -> PerpMarket:
    """Fetch a market by ID.

    - `exchange_market_id`: `<exchange_id>:<market_id>`
    """
    exchange_id, market_id = exchange_market_id.split(':', 1)
    exchange = await self.perp_exchange(exchange_id)
    return await exchange.market(market_id)

  @SDK.method
  async def index(self, market_id: str, /):
    """Fetch the market index price."""
    market = await self.perp_market(market_id)
    return await market.index()

  @SDK.method
  async def next_funding(self, market_id: str, /) -> NextFunding:
    """Fetch the next funding rate and time."""
    market = await self.perp_market(market_id)
    return await market.next_funding()

  @SDK.method
  @PaginatedResponse.lift
  async def funding_rates(
    self, market_id: str, /, start: datetime | None = None, end: datetime | None = None
  ):
    """Fetch the market's historical funding rates.

    Args:
      market_id: Market to fetch rates for.
      start: Start of the window (inclusive). `None` fetches from the earliest available.
      end: End of the window (inclusive). `None` means everything since `start`.
    """
    market = await self.perp_market(market_id)
    async for page in market.funding_rates(start, end):
      yield page

  @SDK.method
  @PaginatedResponse.lift
  async def funding_payments(self, market_id: str, /, start: datetime, end: datetime):
    """Fetch your funding payments history."""
    market = await self.perp_market(market_id)
    async for page in market.funding_payments(start, end):
      yield page

  @SDK.method
  async def perp_position(self, market_id: str, /) -> PerpPosition:
    """Fetch your open position in the perpetual market."""
    market = await self.perp_market(market_id)
    return await market.perp_position()

  @SDK.method
  async def leverage(self, market_id: str, /, *, refetch: bool = False) -> Decimal:
    """Fetch the leverage this account can open at on the selected market.

    - `market_id`: `<exchange_id>:<market_id>`.

    See `PerpMarket.leverage`; cached after the first call.
    """
    market = await self.perp_market(market_id)
    return await market.leverage(refetch=refetch)

  @SDK.method
  async def perp_collateral(self, id: str, /) -> PerpCollateral:
    """Fetch perpetual collateral.

    - 1-segment (`perp`): exchange-level bucket.
    - 2-segment (`perp:BTC-USD`): market-level (mode-aware).
    """
    if ':' in id:
      exchange_id, market_id = id.split(':', 1)
      exchange = await self.perp_exchange(exchange_id)
      return await exchange.perp_collateral(market_id)
    exchange = await self.perp_exchange(id)
    return await exchange.perp_collateral()
