"""The perpetual Market object; market ids are the venue's market names (`BTC-USD`)."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from typing_extensions import Any, AsyncContextManager, AsyncIterable, Sequence
from tribulnation.sdk.core import OverflowPolicy, PaginatedResponse
from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  Fees,
  FundingPayment,
  FundingRate,
  NextFunding,
  Order,
  OrderResponse,
  OrderState,
  PerpCollateral,
  PerpMarket,
  PerpPosition,
  Rules,
  Settings,
  Trade,
)

from ..core import FUNDING_INTERVAL
from . import account, books, history, orders
from .common import Public


@dataclass(frozen=True, kw_only=True)
class ExtendedPerpMarket(Public, PerpMarket):
  """A perpetual market, margined and settled in the sub-account's collateral (`USD`)."""

  name: str
  """The venue's market name, e.g. `BTC-USD`."""
  CANDLE_INTERVALS = history.CANDLE_INTERVALS

  @property
  def market_id(self) -> str:
    """The venue's market name."""
    return self.name

  @property
  def exchange_id(self) -> str:
    """The perpetual exchange."""
    return 'perp'

  async def depth(self, *, levels: int | None = None, settings: Settings = {}) -> Book:
    """The whole aggregated REST book, with no timestamp; on an RFQ market, the first
    snapshot of its quotes stream, stamped with the frame's time.

    Args:
      levels: Keep at most this many levels per side.
      settings: Unused: Extended has no depth settings.

    Raises:
      MissingData: The venue has no book for the market (an inactive market).
    """
    return await books.depth(self.shared, self.name, levels=levels)

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """Maintain the full book (the quotes on an RFQ market) from the venue's snapshot,
    100 ms deltas and minute snapshots; a `seq` gap fails the stream. Consumers of one
    market share a single upstream subscription.

    Args:
      levels: Keep at most this many levels per side.
      queue_size: Books buffered for this subscriber.
      overflow: What to do when the buffer is full.
      settings: Unused: Extended has no depth settings.
    """
    return books.depth_stream(
      self.shared, self.name, levels=levels, queue_size=queue_size, overflow=overflow
    )

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Tick, step and minimum size from `tradingConfig`, and the side-specific price
    band against the mark price: a buy may not exceed mark x (1 + `limitPriceCap`), a
    sell may not go below mark x (1 - `limitPriceFloor`). No standard fee schedule is
    published (`fees` is `None`); `api` is `status == 'ACTIVE'`. Value caps, leverage
    cap and trading hours stay in `details`."""
    m = await self.shared.perp(self.name, refetch=refetch)
    config = m['tradingConfig']
    return Rules(
      fee_asset=m['collateralAssetName'],
      tick_size=config['minPriceChange'],
      step_size=config['minOrderSizeChange'],
      fixed_min_qty=config['minOrderSize'],
      rel_min_price=1 - config['limitPriceFloor'],
      rel_max_price=1 + config['limitPriceCap'],
      fees=None,
      api=m['status'] == 'ACTIVE',
      details={
        'status': m['status'],
        'is_rfq': m['isRfq'],
        'trading_hours': m.get('tradingHours'),
        'max_market_order_value': config['maxMarketOrderValue'],
        'max_limit_order_value': config['maxLimitOrderValue'],
        'max_position_value': config['maxPositionValue'],
        'max_leverage': config['maxLeverage'],
        'max_num_orders': config['maxNumOrders'],
      },
    )

  async def fees(self, *, refetch: bool = False) -> Fees:
    """The sub-account's maker and taker rates on the market, the same for buys and
    sells. The venue charges an RFQ market's orders the taker rate, even resting."""
    rows = await self.shared.call(lambda: self.shared.client.account.fees([self.name]))
    for row in rows:
      if row['market'] == self.name:
        return Fees.symmetric(maker=row['makerFeeRate'], taker=row['takerFeeRate'])
    raise ValueError(f'Extended returned no fee rates for {self.name}')

  def candles(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> PaginatedResponse[Candle]:
    """Trade candles opening in `[start, end)`, newest first; volume in the base asset,
    no quote volume or trade count."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(
      history.candles(self.shared, self.name, interval, start, end)
    )

  async def query_order(self, id: str) -> OrderState | None:
    """Look an order up by Extended id, open or closed."""
    return await orders.query_order(self.shared, self.name, id)

  async def open_orders(self) -> Sequence[OrderState]:
    """The market's open `LIMIT` orders; conditional, TP/SL and TWAP orders are left
    out."""
    return await orders.open_orders(self.shared, self.name)

  def random_client_order_id(self) -> str:
    """32 random hex digits, sent as the order's `externalId`."""
    return orders.random_client_order_id()

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Sign and send an order; RFQ markets go through the RFQ endpoint.

    See `orders.place_order` for the mapping.

    Raises:
      AuthError: The client cannot sign (no Stark private key).
      ValueError: Zero size, non-positive or off-grid price or size, or `POST_ONLY` on
        an RFQ market.
      OrderRejected: The venue refused the order with an error code: nothing rests.
    """
    row = await self.shared.perp(self.name)
    return await orders.place_order(self.shared, row, order)

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """Cancel by Extended id; cancellation is asynchronous."""
    return await orders.cancel_order(self.shared, id)

  async def cancel_orders(self, ids: Sequence[str], *, settings: Settings = {}) -> Any:
    """Cancel by Extended ids, in one mass-cancel request."""
    return await orders.cancel_orders(self.shared, ids)

  async def cancel_open_orders(self, *, settings: Settings = {}) -> Any:
    """Cancel the orders `open_orders` lists, in one mass-cancel request."""
    return await orders.cancel_open_orders(self.shared, self.name)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Personal fills, newest first, with fees in the collateral asset."""
    return PaginatedResponse(history.trades_history(self.shared, self.name, start, end))

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """The account's new fills on this market, from the private account stream."""
    return history.trades_stream(
      self.shared, self.name, queue_size=queue_size, overflow=overflow
    )

  async def perp_position(self, *, ttl: timedelta | None = None) -> PerpPosition:
    """The signed position and entry price."""
    rows = await self.shared.call(
      lambda: self.shared.client.account.positions([self.name])
    )
    return account.perp_position(rows, self.name)

  async def perp_collateral(self, *, ttl: timedelta | None = None) -> PerpCollateral:
    """The sub-account's one cross bucket, whatever the market."""
    return account.bucket(await self.shared.call(self.shared.client.account.balance))

  async def leverage(self, *, ttl: timedelta | None = None) -> Decimal:
    """The sub-account's leverage setting on the market (the venue default until
    changed), read per market and shared for the caller's `ttl`."""
    name = self.name
    rows = await self.shared.reads.read(
      ('leverage', name),
      lambda: self.shared.call(lambda: self.shared.client.account.leverage([name])),
      ttl=ttl,
    )
    for row in rows:
      if row['market'] == name:
        return row['leverage']
    raise ValueError(f'Extended returned no leverage for {name}')

  async def index(self, *, settings: Settings = {}) -> Decimal:
    """The market's index price, fresh from `info.markets`."""
    return (await self.shared.fresh(self.name))['marketStats']['indexPrice']

  async def next_funding(self, *, ttl: timedelta | None = None) -> NextFunding:
    """The venue's one-minute estimate of the next hourly rate (a fraction, positive
    when longs pay) and its payment time. No premium is reported."""
    stats = (await self.shared.fresh(self.name))['marketStats']
    return NextFunding(
      rate=stats['fundingRate'],
      time=stats['nextFundingRate'],
      interval=FUNDING_INTERVAL,
    )

  def funding_rates(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> PaginatedResponse[FundingRate]:
    """Applied hourly rates, newest first, with inclusive bounds."""
    return PaginatedResponse(history.funding_rates(self.shared, self.name, start, end))

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    """The sub-account's hourly funding payments on the market, with inclusive bounds,
    positive when received, in the collateral asset (`USD`).

    Raises:
      ValueError: A bound is not timezone-aware.
    """
    return PaginatedResponse(
      history.funding_payments(self.shared, self.name, start, end)
    )
