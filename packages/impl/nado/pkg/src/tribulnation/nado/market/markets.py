"""The perpetual and spot Market objects; market ids are Nado product symbols
(`BTC-PERP`, `KBTC`)."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from typing_extensions import Any, AsyncContextManager, AsyncIterable, Sequence
from typed_nado.schemas import Symbol
from tribulnation.sdk.core import OverflowPolicy, PaginatedResponse
from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  Fees,
  FundingPayment,
  FundingRate,
  Market,
  NextFunding,
  Order,
  OrderResponse,
  OrderState,
  PerpCollateral,
  PerpMarket,
  PerpPosition,
  Rules,
  Settings,
  SpotBalances,
  SpotMarket,
  SpotRules,
  Trade,
)

from ..core import QUOTE_ASSET, QUOTE_PRODUCT, random_client_order_id, x18
from . import account, books, history, stats
from . import orders as ordering
from .common import Public

TRADABLE = 'live'
"""The trading status under which a market takes every order type; the others
(`post_only`, `reduce_only`, `soft_reduce_only`, `not_tradable`) restrict it."""


def standard_fees(s: Symbol) -> Fees:
  """The product's default maker and taker rates, the same for both sides."""
  return Fees.symmetric(
    maker=x18(s['maker_fee_rate_x18']), taker=x18(s['taker_fee_rate_x18'])
  )


@dataclass(frozen=True, kw_only=True)
class OrderBookMarket(Public, Market):
  """A product on Nado's order book: books, candles, orders and fills are the same
  endpoints for perpetuals and spot."""

  symbol: str
  """The product symbol, the market id."""
  product_id: int
  """The venue's product id, which every request names."""
  CANDLE_INTERVALS = history.CANDLE_INTERVALS

  @property
  def market_id(self) -> str:
    """The product symbol."""
    return self.symbol

  async def details(self, *, refetch: bool = False) -> Symbol:
    """The product's trading configuration."""
    return await self.shared.symbol(self.symbol, refetch=refetch)

  async def depth(self, *, levels: int | None = None, settings: Settings = {}) -> Book:
    """The aggregated book, at most 100 levels per side (the venue's limit)."""
    return await books.depth(self.shared, self.product_id, levels=levels)

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """A 100-level snapshot kept current by the `book_depth` diffs (about every 50 ms),
    shared by every consumer of the market; at most 100 levels per side."""
    return books.depth_stream(
      self.shared,
      self.product_id,
      levels=levels,
      queue_size=queue_size,
      overflow=overflow,
    )

  def candles(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> PaginatedResponse[Candle]:
    """Trade candles opening in `[start, end)`, newest first, up to 500 per page, with
    base volume only."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(
      history.candles(self.shared, self.product_id, interval, start, end)
    )

  async def fees(self, *, refetch: bool = False) -> Fees:
    """The subaccount's maker and taker rates on this product (`fee_rates`)."""
    return await account.fees(self.shared, self.product_id)

  async def query_order(self, id: str) -> OrderState | None:
    """Look an order up by digest: on the book, else in the archive (orders that
    filled at least once); an order cancelled unfilled is `None`."""
    return await ordering.query_order(self.shared, self.product_id, id)

  async def open_orders(self) -> Sequence[OrderState]:
    """The subaccount's resting orders on this product."""
    return await ordering.open_orders(self.shared, self.product_id)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Personal fills with `start <= time <= end`, newest first, fees in USDT0."""
    return PaginatedResponse(
      history.trades_history(self.shared, self.product_id, start, end)
    )

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """The subaccount's new fills on this product (the public `fill` stream)."""
    return history.trades_stream(
      self.shared, self.product_id, queue_size=queue_size, overflow=overflow
    )

  def random_client_order_id(self) -> str:
    """A fresh client order id: a decimal integer below `2^63`."""
    return random_client_order_id()

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Place a `LIMIT` (resting until cancelled), `POST_ONLY` or `MARKET` order (an
    immediate-or-cancel limit at `price`, the worst acceptable); the id is its digest.

    Spot orders never borrow unless `settings={'nado': {'spot_leverage': True}}`.

    Raises:
      AuthError: The client has no key to sign with.
      OrderRejected: The venue refused the order (off-tick price, size off the step,
        below the minimum notional, health, a crossing post-only order, an IOC that
        does not cross, ...).
    """
    return await ordering.place_order(
      self.shared, await self.details(), order, settings
    )

  async def place_orders(
    self, orders: Sequence[Order], *, settings: Settings = {}
  ) -> Sequence[OrderResponse | Exception]:
    """Place several orders in one `place_orders` request, processed independently;
    a refused one is its `OrderRejected`."""
    return await ordering.place_orders(
      self.shared, await self.details(), orders, settings
    )

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """Cancel by digest.

    Raises:
      OrderNotFound: The order is no longer on the book.
    """
    return await ordering.cancel_order(self.shared, self.product_id, id)

  async def cancel_orders(self, ids: Sequence[str], *, settings: Settings = {}) -> Any:
    """Cancel by digests, in one signed request."""
    return await ordering.cancel_orders(self.shared, self.product_id, ids)

  async def replace_order(
    self, id: str, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Cancel `id` and place `order` in one atomic `cancel_and_place`."""
    return await ordering.replace_order(
      self.shared, await self.details(), id, order, settings
    )

  async def cancel_open_orders(self, *, settings: Settings = {}) -> Any:
    """The venue's cancel-all, scoped to this product."""
    return await ordering.cancel_open_orders(self.shared, self.product_id)


@dataclass(frozen=True, kw_only=True)
class NadoPerpMarket(OrderBookMarket, PerpMarket):
  """A USDT0-settled perpetual on the subaccount's unified cross margin."""

  @property
  def exchange_id(self) -> str:
    """The perpetual exchange."""
    return 'perp'

  async def rules(self, *, refetch: bool = False) -> Rules:
    """The product's tick, size step and minimum notional (`min_size`, in USDT0), with
    its default rates; fees are charged in USDT0. `api` is true only while the market
    is `live`."""
    s = await self.details(refetch=refetch)
    return Rules(
      fee_asset=QUOTE_ASSET,
      tick_size=x18(s['price_increment_x18']),
      step_size=x18(s['size_increment']),
      min_value=x18(s['min_size']),
      fees=standard_fees(s),
      api=s['trading_status'] == TRADABLE,
      details=s,
    )

  async def perp_position(self, *, ttl: timedelta | None = None) -> PerpPosition:
    """The signed cross position, at the archive's average entry price.

    Raises:
      NotImplementedError: The market holds an isolated position.
    """
    return await account.perp_position(
      self.shared, self.symbol, self.product_id, ttl=ttl
    )

  async def perp_collateral(self, *, ttl: timedelta | None = None) -> PerpCollateral:
    """The subaccount's cross bucket (its whole unified margin).

    Raises:
      NotImplementedError: The market holds an isolated position.
    """
    return await account.market_bucket(
      self.shared, self.symbol, self.product_id, ttl=ttl
    )

  async def leverage(self, *, ttl: timedelta | None = None) -> Decimal:
    """The leverage the product's initial risk weights allow on cross margin."""
    return await account.leverage(self.shared, self.product_id)

  async def collateral_id(self) -> str:
    """USDT0's spot collateral id, `<account_id>:spot:USDT0`: the subaccount is one
    unified account, and the USDT0 its spot markets spend is what margins every
    perpetual (ADR 0051)."""
    return f'{self.account_id}:spot:{QUOTE_ASSET}'

  async def index(self, *, settings: Settings = {}) -> Decimal:
    """The index price."""
    return await stats.index(self.shared, self.product_id)

  async def next_funding(self, *, ttl: timedelta | None = None) -> NextFunding:
    """The predicted rate of the next hourly settlement, positive when longs pay."""
    return await stats.next_funding(self.shared, self.product_id)

  def funding_rates(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> PaginatedResponse[FundingRate]:
    """Realized hourly rates, oldest first, positive when longs pay."""
    return PaginatedResponse(
      history.funding_rates(self.shared, self.product_id, start, end)
    )

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    """Personal funding payments, received-positive, newest first."""
    return PaginatedResponse(
      history.market_funding_payments(self.shared, self.product_id, start, end)
    )


@dataclass(frozen=True, kw_only=True)
class NadoSpotMarket(OrderBookMarket, SpotMarket):
  """A spot asset traded against USDT0 on the subaccount's balances."""

  @property
  def exchange_id(self) -> str:
    """The spot exchange."""
    return 'spot'

  async def rules(self, *, refetch: bool = False) -> SpotRules:
    """The product's tick, size step and minimum notional (`min_size`, in USDT0), with
    its default rates; fees are charged in USDT0."""
    s = await self.details(refetch=refetch)
    return SpotRules(
      base=self.symbol,
      quote=QUOTE_ASSET,
      fee_asset=QUOTE_ASSET,
      tick_size=x18(s['price_increment_x18']),
      step_size=x18(s['size_increment']),
      min_value=x18(s['min_size']),
      fees=standard_fees(s),
      api=s['trading_status'] == TRADABLE,
      details=s,
    )

  async def balances(self, *, ttl: timedelta | None = None) -> SpotBalances:
    """The base and USDT0 balances, from one `subaccount_info`."""
    info = await account.summary(self.shared, ttl=ttl)
    return SpotBalances(
      base=account.spot_balance(info, self.product_id),
      quote=account.spot_balance(info, QUOTE_PRODUCT),
    )
