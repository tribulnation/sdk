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
from datetime import datetime, timedelta
from decimal import Decimal

from tribulnation.sdk.core import SDK, PaginatedResponse, OverflowPolicy
from .types import (
  Book,
  Candle,
  CandleInterval,
  Collateral,
  PerpCollateral,
  SpotBalances,
  SpotCollateralIds,
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
  SpotRules,
  Fees,
  Ticker,
  PerpStats,
)
from .settings import Settings
from .market import Market, SpotMarket, PerpMarket, open_trades_stream
from .exchange import Exchange, SpotExchange, PerpExchange
from .venue import TradingVenue
from .ids import QualifiedExchangeId, QualifiedMarketId


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
    qualified = QualifiedExchangeId.parse(id)
    venue = await self.venue(qualified.account_id)
    return await venue.exchange(qualified.exchange_id)

  @SDK.method
  async def spot_exchange(self, id: str, /) -> SpotExchange:
    """Fetch a spot exchange by ID.

    - `id`: `<account_id>:<exchange_id>`
    """
    qualified = QualifiedExchangeId.parse(id)
    venue = await self.venue(qualified.account_id)
    return await venue.spot_exchange(qualified.exchange_id)

  @SDK.method
  async def perp_exchange(self, id: str, /) -> PerpExchange:
    """Fetch a perpetual exchange by ID.

    - `id`: `<account_id>:<exchange_id>`
    """
    qualified = QualifiedExchangeId.parse(id)
    venue = await self.venue(qualified.account_id)
    return await venue.perp_exchange(qualified.exchange_id)

  @SDK.method
  async def market(self, id: str, /) -> Market:
    """Fetch a market by ID.

    - `id`: `<account_id>:<exchange_id>:<market_id>`
    """
    qualified = QualifiedMarketId.parse(id)
    venue = await self.venue(qualified.account_id)
    exchange = await venue.exchange(qualified.exchange_id)
    return await exchange.market(qualified.market_id)

  @SDK.method
  async def spot_market(self, id: str, /) -> SpotMarket:
    """Fetch a spot market by ID.

    - `id`: `<account_id>:<exchange_id>:<market_id>`
    """
    qualified = QualifiedMarketId.parse(id)
    venue = await self.venue(qualified.account_id)
    exchange = await venue.spot_exchange(qualified.exchange_id)
    return await exchange.market(qualified.market_id)

  @SDK.method
  async def perp_market(self, id: str, /) -> PerpMarket:
    """Fetch a perpetual market by ID.

    - `id`: `<account_id>:<exchange_id>:<market_id>`
    """
    qualified = QualifiedMarketId.parse(id)
    venue = await self.venue(qualified.account_id)
    exchange = await venue.perp_exchange(qualified.exchange_id)
    return await exchange.market(qualified.market_id)

  @SDK.method
  async def depth(
    self, market_id: str, /, *, levels: int | None = None, settings: Settings = {}
  ) -> Book:
    """Fetch the market order book, bids and asks best-first.

    Args:
      levels: Cap the number of levels per side. `None` returns the full book.
      settings: Venue-specific options keyed by venue name, e.g.
        `{'hyperliquid': {'depth_source': 'bbo'}}`; each venue reads only its own key.
    """
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

    A venue fans one shared upstream out to every subscriber through a bounded
    per-subscriber queue. The defaults keep only the freshest book; pass
    `overflow='fail'` with a larger `queue_size` to capture every book. The polling
    fallback used by generic markets ignores both.

    Args:
      levels: Cap the number of levels per side. `None` streams the full book.
      queue_size: Books buffered for this subscriber.
      overflow: `'latest'` silently drops stale books when the buffer is full;
        `'fail'` raises `NetworkError` instead, so you can reconnect.
      settings: Venue-specific options keyed by venue name, e.g.
        `{'hyperliquid': {'depth_source': 'bbo'}}` to pick a venue's depth feed;
        each venue reads only its own key. Different feeds are different
        streams and need not agree tick-for-tick.
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
    ttl: timedelta | None = None,
  ) -> Mapping[str, Ticker]:
    """Fetch a top-of-book snapshot for many markets at once.

    Defined on the exchange, not on a single market. The default fans out over the
    individual markets with `asyncio.gather`; venues that can fetch the whole universe in
    one request override it, which yields a consistent cross-section at one instant
    instead of a snapshot spread over minutes of wall clock.

    Native 24h volumes are returned in `base_volume_24h` and `quote_volume_24h`,
    in base and quote currency respectively. Each is `None` when unavailable;
    zero is a reported zero. Quote volume is not normalized to USD or estimated
    from the latest price. The venue defines the trailing 24h window.

    Args:
      exchange: `<account_id>:<exchange_id>`.
      markets: Market IDs to fetch. `None` fetches every market of the exchange.
      settings: Venue-specific ticker settings.
      ttl: How old a shared answer may be; `None` asks afresh. See `Market`.

    Returns:
      A mapping of market ID to its `Ticker`.
    """
    sdk = await self.exchange(exchange)
    return await sdk.tickers(markets=markets, settings=settings, ttl=ttl)

  @SDK.method
  async def perp_stats(
    self,
    exchange: str,
    *,
    markets: Collection[str] | None = None,
    settings: Settings = {},
    ttl: timedelta | None = None,
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
      ttl: How old a shared answer may be; `None` asks afresh. See `Market`.

    Returns:
      A mapping of market ID to its `PerpStats`.
    """
    sdk = await self.perp_exchange(exchange)
    return await sdk.perp_stats(markets=markets, settings=settings, ttl=ttl)

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
  async def spot_rules(self, market_id: str, /, *, refetch: bool = False) -> SpotRules:
    """Fetch a spot market's rules, which also name its `base` and `quote` asset IDs."""
    market = await self.spot_market(market_id)
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
  ) -> AsyncIterable[Sequence[Candle]]:
    """Fetch the market's historical trade candles, paginated: async-iterate the pages.

    Ordering within and across pages follows the venue. Opening timestamps are not
    repeated across pages; page sizes can vary. `Candle.time` is always the open time;
    prices and volumes are `Decimal`, `quote_volume` and `trades` are `None` where the
    venue reports none. Only trade candles: mark and index series are not exposed. A
    candle may still be forming; an elapsed interval does not guarantee immutable data.

    Each implementation declares the widths it serves in `Market.CANDLE_INTERVALS`;
    any other `interval` raises `ValueError` before a request is made.

    Args:
      interval: Candle width, one of `'1m'`, `'5m'`, `'15m'`, `'1h'`, `'4h'`, `'1d'`.
      start: Inclusive lower bound on opening time, as a timezone-aware datetime.
      end: Exclusive upper bound on opening time, as a timezone-aware datetime.
        Equal bounds produce no candles.
    """
    market = await self.market(market_id)
    async for page in market.candles(interval, start, end):
      yield page

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
    settings: Settings = {},
  ) -> AsyncGenerator[AsyncIterable[Trade]]:
    """Subscribe to your real-time fills.

    Same fan-out as `depth_stream`, but the defaults buffer generously and fail on
    overflow rather than dropping your own fills silently.

    Args:
      queue_size: Trades buffered for this subscriber.
      overflow: `'fail'` raises `NetworkError` when the buffer is full; `'latest'`
        silently keeps only the newest trade.
      settings: Venue-specific options keyed by venue name, e.g.
        `{'dydx': {'trades_source': 'fastest'}}` to pick a venue's fill source;
        each venue reads only its own key.
    """
    market = await self.market(market_id)
    async with open_trades_stream(
      market, queue_size=queue_size, overflow=overflow, settings=settings
    ) as stream:
      yield stream

  @SDK.method
  async def collateral(self, id: str, /, *, ttl: timedelta | None = None) -> Collateral:
    """Resolve a collateral ID: the money that funds new orders, as `equity` and
    `free_collateral`.

    Markets name their IDs: `collateral_ids()` on a spot market (its base and quote
    assets) and `collateral_id()` on a perpetual market. Markets sharing money return
    the same ID, so reserving per ID never counts it twice (ADR 0051).

    - `<account_id>:<exchange_id>:<asset>` (`mt:spot:USDC`, or `hl:spot:0` where the
      venue's asset IDs are indices): a spot asset; `equity` is its total balance and
      `free_collateral` what open orders do not hold.
    - `<account_id>:<exchange_id>` (`dydx:perp`): a perpetual exchange's pool, as
      `PerpCollateral`.

    For the bucket backing one perpetual market (mode-aware, isolated included), use
    `perp_collateral(<market id>)`.

    Raises:
      ValueError: The ID names a spot exchange without an asset, or a perpetual
        exchange with one.

    Args:
      ttl: How old a shared answer may be; `None` asks afresh. See `Market`.
    """
    account_id, rest = id.split(':', 1)
    venue = await self.venue(account_id)
    return await venue.collateral(rest, ttl=ttl)

  @SDK.method
  async def balances(
    self, market_id: str, /, *, ttl: timedelta | None = None
  ) -> SpotBalances:
    """Fetch your base and quote balances on a spot market.

    Each is a `Balance(total, free)`: `free` excludes what open orders hold, so it is
    the base a sell can spend and the quote a buy can spend.

    Args:
      ttl: How old a shared answer may be; `None` asks afresh. See `Market`.
    """
    market = await self.spot_market(market_id)
    return await market.balances(ttl=ttl)

  @SDK.method
  async def collateral_ids(self, market_id: str, /) -> SpotCollateralIds:
    """The collateral IDs a spot market's orders reserve on: a buy on `quote`, a sell
    on `base`. Resolve them with `collateral()`."""
    market = await self.spot_market(market_id)
    return await market.collateral_ids()

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
      order: `qty` in signed base units (positive buys, negative sells), `price`,
        `type`, and an optional `client_order_id` of your own: fills report it back
        as `Trade.client_order_id` on venues with client order IDs, and the rest
        ignore it.
      settings: Venue-specific options keyed by venue name, e.g. `{'dydx': {...}}`; see
        each venue page for accepted keys.

    Raises:
      OrderRejected: The venue definitively refused the order: nothing rests and
        nothing filled, so it is safe to treat as dead.
      ApiError: Any other venue error; it may be ambiguous (e.g. a 5xx), so the order
        may have been placed.
      NetworkError: The venue could not be reached or timed out; the order may have
        been placed.
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
  async def position(
    self, market_id: str, /, *, ttl: timedelta | None = None
  ) -> Position:
    """Fetch your open position in a perpetual market, as a signed size in base units.

    The same data as `perp_position()`, typed as the base `Position`. Spot markets have
    balances instead: see `balances()`.

    Args:
      ttl: How old a shared answer may be; `None` asks afresh. See `Market`.
    """
    market = await self.perp_market(market_id)
    return await market.position(ttl=ttl)

  @SDK.method
  async def collateral_id(self, market_id: str, /) -> str:
    """The collateral ID of the money funding new orders on a perpetual market.

    A margin pool (`dydx:perp`), or on a unified account the collateral token's spot
    ID (`hl:spot:0`: USDC, by token index). Isolated positions return the pool new
    margin is drawn from.
    Resolve it with `collateral()`.
    """
    market = await self.perp_market(market_id)
    return await market.collateral_id()

  @SDK.method
  async def available_notional(
    self, market_id: str, /, *, ttl: timedelta | None = None
  ) -> Decimal:
    """Fetch the maximum notional position you could open right now on a perpetual
    market.

    The free collateral of the bucket backing the market times the account's
    `leverage()` on it, unless the venue publishes a more precise figure. This is
    opening capacity, deliberately separate from `perp_collateral()`, which is about
    liquidation distance. Spot capacity is `balances()`.

    Args:
      ttl: How old a shared answer may be; `None` asks afresh. See `Market`.
    """
    market = await self.perp_market(market_id)
    return await market.available_notional(ttl=ttl)

  @SDK.method
  async def perp_position(
    self, market_id: str, /, *, ttl: timedelta | None = None
  ) -> PerpPosition:
    """Fetch your open perpetual position: signed `size` plus average `entry_price`.

    Args:
      ttl: How old a shared answer may be; `None` asks afresh. See `Market`.
    """
    market = await self.perp_market(market_id)
    return await market.perp_position(ttl=ttl)

  @SDK.method
  async def leverage(
    self, market_id: str, /, *, ttl: timedelta | None = None
  ) -> Decimal:
    """Fetch the leverage this account can open at on a perpetual market.

    The multiple of free collateral the account can open as notional: opening `n` of
    notional needs `n / leverage` of collateral. Account-specific (e.g. a per-market
    leverage setting), so it is not part of `rules()`.
    Spot markets have no leverage; unsupported venues raise `NotImplementedError`.

    Args:
      ttl: How old a shared answer may be; `None` asks afresh. See `Market`.
    """
    market = await self.perp_market(market_id)
    return await market.leverage(ttl=ttl)

  @SDK.method
  async def perp_collateral(
    self, id: str, /, *, ttl: timedelta | None = None
  ) -> PerpCollateral:
    """Fetch the perpetual collateral bucket, with maintenance-margin risk fields.

    Same bucket model and routing as `collateral()`, plus `initial_margin`,
    `maintenance_margin`, `leverage`, `margin_mode`, and the `initial_ratio` and
    `maintenance_ratio` properties. You can't open more at `initial_ratio >= 1`;
    liquidation is at `maintenance_ratio >= 1`.

    Args:
      id: `<account_id>:<exchange_id>` for the exchange bucket, or
        `<account_id>:<exchange_id>:<market_id>` for the bucket backing that market.
      ttl: How old a shared answer may be; `None` asks afresh. See `Market`.
    """
    parts = id.split(':', 2)
    if len(parts) == 3:
      account_id, exchange_id, market_id = parts
      venue = await self.venue(account_id)
      exchange = await venue.perp_exchange(exchange_id)
      return await exchange.perp_collateral(market_id, ttl=ttl)
    account_id, exchange_id = parts
    venue = await self.venue(account_id)
    exchange = await venue.perp_exchange(exchange_id)
    return await exchange.perp_collateral(ttl=ttl)

  @SDK.method
  async def index(self, market_id: str, /) -> Decimal:
    """Fetch the market index (oracle) price."""
    market = await self.perp_market(market_id)
    return await market.index()

  @SDK.method
  async def next_funding(
    self, market_id: str, /, *, ttl: timedelta | None = None
  ) -> NextFunding:
    """Fetch the upcoming funding `rate`, `time` and `interval`.

    `.annualized` extrapolates the rate to a yearly figure.

    Args:
      ttl: How old a shared answer may be; `None` asks afresh. See `Market`.
    """
    market = await self.perp_market(market_id)
    return await market.next_funding(ttl=ttl)

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

    Received is positive, paid is negative, in quote units. Credential-scoped, unlike
    `funding_rates`.

    Args:
      start: Start of the window (inclusive).
      end: End of the window (inclusive).
    """
    market = await self.perp_market(market_id)
    async for page in market.funding_payments(start, end):
      yield page
