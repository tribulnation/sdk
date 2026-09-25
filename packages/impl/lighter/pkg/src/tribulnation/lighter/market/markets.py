"""Perpetual and spot Market objects; market ids are the venue's numeric `market_id`."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import asyncio

from typing_extensions import Any, AsyncContextManager, AsyncIterable, Sequence
from tribulnation.sdk.core import ApiError, OverflowPolicy, PaginatedResponse
from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  Collateral,
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
  Position,
  Rules,
  Settings,
  Trade,
)

from ..core import FEE_TICK, USDC, percent
from . import account, books, history, orders, stats
from .common import Public


@dataclass(frozen=True, kw_only=True)
class MarketBase(Public, Market):
  """What perp and spot markets share: identity, books, orders, fills and fees."""

  market_index: int
  """The venue's market id."""
  CANDLE_INTERVALS = history.CANDLE_INTERVALS

  @property
  def market_id(self) -> str:
    """The venue's market id, as a decimal string."""
    return str(self.market_index)

  async def depth(self, *, levels: int | None = None) -> Book:
    """The book from the top 250 resting orders per side, summed per price."""
    return await books.depth(self.shared, self.market_index, levels=levels)

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """The full book, maintained from the `order_book` snapshot and 50 ms deltas."""
    return books.depth_stream(
      self.shared,
      self.market_index,
      levels=levels,
      queue_size=queue_size,
      overflow=overflow,
    )

  async def fees(self, *, refetch: bool = False) -> Fees:
    """The account's current fee ticks (`account/limits`), the same for buys and sells
    and for perp and spot fills."""
    account_index = self.shared.account_index
    limits = await self.shared.call(
      lambda: self.shared.client.api.account.limits(account_index)
    )
    return Fees.symmetric(
      maker=limits['current_maker_fee_tick'] * FEE_TICK,
      taker=limits['current_taker_fee_tick'] * FEE_TICK,
    )

  def candles(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> PaginatedResponse[Candle]:
    """Trade candles opening in `[start, end)`; zero volumes are omitted by the venue."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(
      history.candles(self.shared, self.market_index, interval, start, end)
    )

  async def query_order(self, id: str) -> OrderState | None:
    """Look the order up by client index (active, or inactive within 24h)."""
    return await orders.query_order(self.shared, self.market_index, id)

  async def open_orders(self) -> Sequence[OrderState]:
    """The market's active orders."""
    return await orders.open_orders(self.shared, self.market_index)

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Place a limit, post-only or market order; the id is its client order index."""
    return await orders.place_order(
      self.shared, self.market_index, order, settings=settings
    )

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """Cancel by client order index."""
    return await orders.cancel_order(self.shared, self.market_index, id)


@dataclass(frozen=True, kw_only=True)
class LighterPerpMarket(MarketBase, PerpMarket):
  """A perpetual market, settled in USDC."""

  @property
  def exchange_id(self) -> str:
    """The perpetual exchange."""
    return 'perp'

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Signing scales, order floors and the standard account's rates (zero)."""
    d = await self.shared.perp(self.market_index, refetch=refetch)
    maker = percent(d['maker_fee']) if d['is_maker_fee_enabled'] else Decimal(0)
    taker = percent(d['taker_fee']) if d['is_taker_fee_enabled'] else Decimal(0)
    return Rules(
      fee_asset=str(USDC),
      tick_size=Decimal(1).scaleb(-d['supported_price_decimals']),
      step_size=Decimal(1).scaleb(-d['supported_size_decimals']),
      fixed_min_qty=d['min_base_amount'],
      min_value=d['min_quote_amount'],
      fees=Fees.symmetric(maker=maker, taker=taker),
      api=d['status'] == 'active',
      details=d,
    )

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Personal fills, with fees in USDC."""
    return PaginatedResponse(
      history.trades_history(
        self.shared, 'perp', self.market_index, start, end, fee=history.perp_fee
      )
    )

  def trades_stream(
    self, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """The account's new fills on this market."""
    return history.trades_stream(
      self.shared,
      self.market_index,
      fee=history.perp_fee,
      queue_size=queue_size,
      overflow=overflow,
    )

  async def cancel_open_orders(self, *, settings: Settings = {}) -> Any:
    """The venue's cancel-all, scoped to this market."""
    market_index = self.market_index
    return await self.shared.call(
      lambda: self.shared.client.tx.cancel_all_orders(
        {'mode': 'immediate', 'market_index': market_index}
      )
    )

  async def perp_position(self) -> PerpPosition:
    """The signed position and average entry."""
    return account.perp_position(await self.shared.account(), self.market_index)

  async def perp_collateral(self) -> PerpCollateral:
    """This market's isolated bucket when its position is isolated, else cross."""
    acct, detail = await asyncio.gather(
      self.shared.account(), self.shared.perp(self.market_index)
    )
    return account.market_bucket(acct, self.market_index, detail)

  async def available_notional(self) -> Decimal:
    """Free cross collateral times this market's configured leverage."""
    acct, detail = await asyncio.gather(
      self.shared.account(), self.shared.perp(self.market_index)
    )
    return account.perp_available_notional(acct, self.market_index, detail)

  async def index(self, *, settings: Settings = {}) -> Decimal:
    """The market's index price, fresh from `orderBookDetails`."""
    market_index = self.market_index
    details = await self.shared.call(
      lambda: self.shared.client.api.markets.order_book_details(market_index)
    )
    rows = details['order_book_details'] or []
    if not rows:
      raise ApiError(f'Lighter returned no details for market {market_index}')
    return rows[0]['index_price']

  async def next_funding(self) -> NextFunding:
    """The predicted rate of the next hourly settlement."""
    return await stats.next_funding(self.shared, self.market_index)

  def funding_rates(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> PaginatedResponse[FundingRate]:
    """Hourly settlements, signed by the paying side (longs paying is positive)."""
    return PaginatedResponse(
      history.funding_rates(self.shared, self.market_index, start, end)
    )

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    """Personal funding payments, paid-positive."""
    return PaginatedResponse(
      history.funding_payments(self.shared, self.market_index, start, end)
    )


@dataclass(frozen=True, kw_only=True)
class LighterSpotMarket(MarketBase):
  """A spot market; fees are charged in the asset each fill delivers."""

  base_asset: int
  """The base asset id."""
  quote_asset: int
  """The quote asset id."""

  @property
  def exchange_id(self) -> str:
    """The spot exchange."""
    return 'spot'

  @property
  def fee(self) -> history.Fee:
    """Spot fees: in the base asset on buys, the quote asset on sells."""
    return history.spot_fee(lambda _: self.base_asset, lambda _: self.quote_asset)

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Signing scales, order floors and the standard account's rates (zero). The fee
    asset depends on the fill (ADR 0028)."""
    d = await self.shared.spot(self.market_index, refetch=refetch)
    maker = percent(d['maker_fee']) if d['is_maker_fee_enabled'] else Decimal(0)
    taker = percent(d['taker_fee']) if d['is_taker_fee_enabled'] else Decimal(0)
    return Rules(
      fee_asset=None,
      tick_size=Decimal(1).scaleb(-d['supported_price_decimals']),
      step_size=Decimal(1).scaleb(-d['supported_size_decimals']),
      fixed_min_qty=d['min_base_amount'],
      min_value=d['min_quote_amount'],
      fees=Fees.symmetric(maker=maker, taker=taker),
      api=d['status'] == 'active',
      details=d,
    )

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Personal fills, with fees in the received asset."""
    return PaginatedResponse(
      history.trades_history(
        self.shared, 'spot', self.market_index, start, end, fee=self.fee
      )
    )

  def trades_stream(
    self, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """The account's new fills on this market."""
    return history.trades_stream(
      self.shared,
      self.market_index,
      fee=self.fee,
      queue_size=queue_size,
      overflow=overflow,
    )

  async def position(self) -> Position:
    """The base asset's balance."""
    return account.spot_position(await self.shared.account(), self.base_asset)

  async def collateral(self) -> Collateral:
    """The quote asset's collateral (unified accounts only)."""
    return account.spot_collateral(await self.shared.account(), self.quote_asset)

  async def available_notional(self) -> Decimal:
    """The free quote balance (unified accounts only)."""
    return (await self.collateral()).free_collateral
