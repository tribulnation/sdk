from typing_extensions import (
  Any,
  AsyncIterable,
  AsyncGenerator,
  Sequence,
  Collection,
  Mapping,
)
from abc import abstractmethod
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.core import SDK, PaginatedResponse, OverflowPolicy
from .types import (
  Book,
  Collateral,
  PerpCollateral,
  FundingRate,
  NextFunding,
  FundingPayment,
  Order,
  OrderResponse,
  OrderState,
  Position,
  PerpPosition,
  Trade,
  Rules,
  Ticker,
  PerpStats,
)
from .settings import Settings
from .market import Market, PerpMarket
from .exchange import Exchange, PerpExchange
from .venue import TradingVenue


class TradingMarkets(SDK):
  """A collection of all venues supported by the SDK."""

  @SDK.method
  @abstractmethod
  async def venue(self, id: str, /) -> TradingVenue:
    """Fetch a venue by account ID."""

  @SDK.method
  @abstractmethod
  async def venues(self) -> Sequence[str]:
    """List configured account IDs."""

  @SDK.method
  async def exchange(self, id: str, /) -> Exchange:
    """Fetch an exchange by ID.

    - `id`: `<account_id>:<exchange_id>`
    """
    account_id, exchange_id = id.split(':', 1)
    venue = await self.venue(account_id)
    return await venue.exchange(exchange_id)

  @SDK.method
  async def perp_exchange(self, id: str, /) -> PerpExchange:
    """Fetch a perpetual exchange by ID.

    - `id`: `<account_id>:<exchange_id>`
    """
    account_id, exchange_id = id.split(':', 1)
    venue = await self.venue(account_id)
    return await venue.perp_exchange(exchange_id)

  @SDK.method
  async def market(self, id: str, /) -> Market:
    """Fetch a market by ID.

    - `id`: `<account_id>:<exchange_id>:<market_id>`
    """
    account_id, exchange_id, market_id = id.split(':', 2)
    venue = await self.venue(account_id)
    exchange = await venue.exchange(exchange_id)
    return await exchange.market(market_id)

  @SDK.method
  async def perp_market(self, id: str, /) -> PerpMarket:
    """Fetch a perpetual market by ID.

    - `id`: `<account_id>:<exchange_id>:<market_id>`
    """
    account_id, exchange_id, market_id = id.split(':', 2)
    venue = await self.venue(account_id)
    exchange = await venue.perp_exchange(exchange_id)
    return await exchange.market(market_id)

  @SDK.method
  async def depth(self, market_id: str, /, *, levels: int | None = None) -> Book:
    """Fetch the market order book, bids and asks best-first.

    Args:
      levels: Cap the number of levels per side. `None` returns the full book.
    """
    market = await self.market(market_id)
    return await market.depth(levels=levels)

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
  ) -> AsyncGenerator[AsyncIterable[Book]]:
    """Subscribe to the market order book.

    A venue fans one shared upstream out to every subscriber through a bounded
    per-subscriber queue. The defaults keep only the freshest book; pass
    `overflow='fail'` with a larger `queue_size` to capture every book. The polling
    fallback used by generic markets ignores both.

    Args:
      levels: Cap the number of levels per side. `None` streams the full book.
      queue_size: Books buffered for this subscriber.
      overflow: `'latest'` silently drops stale books when the buffer is full;
        `'fail'` raises `NetworkError` instead, so you can reconnect.
    """
    market = await self.market(market_id)
    async with market.depth_stream(
      levels=levels, queue_size=queue_size, overflow=overflow
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
    """Fetch a top-of-book snapshot for many markets at once.

    Defined on the exchange, not on a single market. The default fans out over the
    individual markets with `asyncio.gather`; venues that can fetch the whole universe in
    one request override it, which yields a consistent cross-section at one instant
    instead of a snapshot spread over minutes of wall clock.

    Args:
      exchange: `<account_id>:<exchange_id>`.
      markets: Market IDs to fetch. `None` fetches every market of the exchange.
      settings: Venue-specific ticker settings.

    Returns:
      A mapping of market ID to its `Ticker`.
    """
    sdk = await self.exchange(exchange)
    return await sdk.tickers(markets=markets, settings=settings)

  @SDK.method
  async def perp_stats(
    self,
    exchange: str,
    *,
    markets: Collection[str] | None = None,
    settings: Settings = {},
  ) -> Mapping[str, PerpStats]:
    """Fetch a pricing and funding snapshot for many perpetual markets at once.

    Index and mark price, predicted funding, next funding time and interval, and open
    interest per market. Like `tickers`, the default fans out per market; venues that can
    fetch the whole universe in one request override it, so the cross-section is
    consistent, which is what cross-market basis and funding analysis needs.

    Args:
      exchange: `<account_id>:<exchange_id>`.
      markets: Market IDs to fetch. `None` fetches every market of the exchange.
      settings: Venue-specific settings.

    Returns:
      A mapping of market ID to its `PerpStats`.
    """
    sdk = await self.perp_exchange(exchange)
    return await sdk.perp_stats(markets=markets, settings=settings)

  @SDK.method
  async def rules(self, market_id: str, /, *, refetch: bool = False) -> Rules:
    """Fetch the market rules: tick and step sizes, fees, min/max, rounding helpers.

    Cached after the first call.

    Args:
      refetch: Fetch again even if the rules are already cached.
    """
    market = await self.market(market_id)
    return await market.rules(refetch=refetch)

  @SDK.method
  async def query_order(self, market_id: str, /, id: str) -> OrderState | None:
    """Fetch the state of the order with the given ID.

    The base implementation scans `open_orders()`, so it only finds open orders unless
    the venue overrides it.
    """
    market = await self.market(market_id)
    return await market.query_order(id)

  @SDK.method
  async def open_orders(self, market_id: str, /) -> Sequence[OrderState]:
    """Fetch your currently open orders."""
    market = await self.market(market_id)
    return await market.open_orders()

  @SDK.method
  @PaginatedResponse.lift
  async def trades_history(
    self, market_id: str, /, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Trade]]:
    """Fetch your fills over a window, paginated: async-iterate the pages.

    Args:
      start: Start of the window (inclusive).
      end: End of the window (inclusive).
    """
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
  ) -> AsyncGenerator[AsyncIterable[Trade]]:
    """Subscribe to your real-time fills.

    Same fan-out as `depth_stream`, but the defaults buffer generously and fail on
    overflow rather than dropping your own fills silently.

    Args:
      queue_size: Trades buffered for this subscriber.
      overflow: `'fail'` raises `NetworkError` when the buffer is full; `'latest'`
        silently keeps only the newest trade.
    """
    market = await self.market(market_id)
    async with market.trades_stream(queue_size=queue_size, overflow=overflow) as stream:
      yield stream

  @SDK.method
  async def position(self, market_id: str, /) -> Position:
    """Fetch your open position in the market, as a signed size in base units.

    On a perpetual market this is the same data as `perp_position()`, typed as the base
    `Position`.
    """
    market = await self.market(market_id)
    return await market.position()

  @SDK.method
  async def collateral(self, id: str, /) -> Collateral:
    """Fetch the collateral bucket backing a market, or an exchange's own bucket.

    A bucket is a set of markets sharing one collateral pool and one liquidation event;
    an exchange is one bucket. Market-level calls are mode-aware: a cross-margin market
    reports the exchange bucket, an isolated market its own. Risk never aggregates across
    buckets. Venues without collateral support raise `NotImplementedError`.

    Args:
      id: `<account_id>:<exchange_id>` for the exchange bucket, or
        `<account_id>:<exchange_id>:<market_id>` for the bucket backing that market.
    """
    parts = id.split(':', 2)
    if len(parts) == 3:
      account_id, exchange_id, market_id = parts
      venue = await self.venue(account_id)
      exchange = await venue.exchange(exchange_id)
      return await exchange.collateral(market_id)
    account_id, exchange_id = parts
    venue = await self.venue(account_id)
    exchange = await venue.exchange(exchange_id)
    return await exchange.collateral()

  @SDK.method
  async def available_notional(self, market_id: str, /) -> Decimal:
    """Fetch the maximum notional position you could open right now.

    Spot: the free quote-token balance. Perps: available collateral times the market's
    maximum leverage. This is opening capacity, deliberately separate from `collateral()`,
    which is about liquidation distance.
    """
    market = await self.market(market_id)
    return await market.available_notional()

  @SDK.method
  async def place_order(
    self, market_id: str, /, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Place an order in the market.

    `LIMIT` rests at `price` unless `settings` request another time-in-force.
    `POST_ONLY` is maker-only: the venue rejects or cancels rather than taking liquidity.
    `MARKET` executes immediately with `price` as the worst acceptable limit; venues
    without native market orders send an aggressive non-resting (IOC) limit, and fills may
    be partial. A venue that can't honor the requested semantics raises rather than
    placing a materially different order.

    Args:
      order: `qty` in signed base units (positive buys, negative sells), `price`, and
        `type`.
      settings: Venue-specific options keyed by venue name, e.g. `{'dydx': {...}}`; see
        each venue page for accepted keys.
    """
    market = await self.market(market_id)
    return await market.place_order(order, settings=settings)

  @SDK.method
  async def place_orders(
    self, market_id: str, /, orders: Sequence[Order], *, settings: Settings = {}
  ) -> Sequence[OrderResponse]:
    """Place several orders concurrently: one response per order, in input order.

    Args:
      orders: The orders to place, each as for `place_order`.
      settings: Venue-specific options, applied to every order.
    """
    market = await self.market(market_id)
    return await market.place_orders(orders, settings=settings)

  @SDK.method
  async def cancel_order(
    self, market_id: str, /, id: str, *, settings: Settings = {}
  ) -> Any:
    """Cancel an order in the market.

    Args:
      id: The order ID, as returned by `place_order`.
      settings: Venue-specific options keyed by venue name.
    """
    market = await self.market(market_id)
    return await market.cancel_order(id, settings=settings)

  @SDK.method
  async def cancel_orders(
    self, market_id: str, /, ids: Sequence[str], *, settings: Settings = {}
  ) -> Any:
    """Cancel several orders concurrently.

    Args:
      ids: The order IDs to cancel.
      settings: Venue-specific options, applied to every cancel.
    """
    market = await self.market(market_id)
    return await market.cancel_orders(ids, settings=settings)

  @SDK.method
  async def cancel_open_orders(
    self, market_id: str, /, *, settings: Settings = {}
  ) -> Any:
    """Cancel everything `open_orders()` returns.

    Args:
      settings: Venue-specific options keyed by venue name.
    """
    market = await self.market(market_id)
    return await market.cancel_open_orders(settings=settings)

  @SDK.method
  async def perp_position(self, market_id: str, /) -> PerpPosition:
    """Fetch your open perpetual position: signed `size` plus average `entry_price`."""
    market = await self.perp_market(market_id)
    return await market.perp_position()

  @SDK.method
  async def perp_collateral(self, id: str, /) -> PerpCollateral:
    """Fetch the perpetual collateral bucket, with maintenance-margin risk fields.

    Same bucket model and routing as `collateral()`, plus `initial_margin`,
    `maintenance_margin`, `leverage`, `margin_mode`, and the `initial_ratio` and
    `maintenance_ratio` properties. You can't open more at `initial_ratio >= 1`;
    liquidation is at `maintenance_ratio >= 1`.

    Args:
      id: `<account_id>:<exchange_id>` for the exchange bucket, or
        `<account_id>:<exchange_id>:<market_id>` for the bucket backing that market.
    """
    parts = id.split(':', 2)
    if len(parts) == 3:
      account_id, exchange_id, market_id = parts
      venue = await self.venue(account_id)
      exchange = await venue.perp_exchange(exchange_id)
      return await exchange.perp_collateral(market_id)
    account_id, exchange_id = parts
    venue = await self.venue(account_id)
    exchange = await venue.perp_exchange(exchange_id)
    return await exchange.perp_collateral()

  @SDK.method
  async def index(self, market_id: str, /) -> Decimal:
    """Fetch the market index (oracle) price."""
    market = await self.perp_market(market_id)
    return await market.index()

  @SDK.method
  async def next_funding(self, market_id: str, /) -> NextFunding:
    """Fetch the upcoming funding `rate`, `time` and `interval`.

    `.annualized` extrapolates the rate to a yearly figure.
    """
    market = await self.perp_market(market_id)
    return await market.next_funding()

  @SDK.method
  @PaginatedResponse.lift
  async def funding_rates(
    self, market_id: str, /, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Sequence[FundingRate]]:
    """Fetch the market's public funding rate history, paginated.

    Each `FundingRate` may also carry the `premium` (mark vs. index) it was computed from.

    Args:
      start: Start of the window (inclusive). `None` fetches from the earliest available.
      end: End of the window (inclusive). `None` means everything since `start`.
    """
    market = await self.perp_market(market_id)
    async for page in market.funding_rates(start, end):
      yield page

  @SDK.method
  @PaginatedResponse.lift
  async def funding_payments(
    self, market_id: str, /, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[FundingPayment]]:
    """Fetch your own settled funding cashflows over a window, paginated.

    Paid is positive, received is negative, in quote units. Credential-scoped, unlike
    `funding_rates`.

    Args:
      start: Start of the window (inclusive).
      end: End of the window (inclusive).
    """
    market = await self.perp_market(market_id)
    async for page in market.funding_payments(start, end):
      yield page
