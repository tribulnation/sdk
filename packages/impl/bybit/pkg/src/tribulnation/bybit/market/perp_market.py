"""Bybit's linear (USDT/USDC-margined) perpetual market (`category='linear'`)."""

from typing_extensions import Any, AsyncContextManager, AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from tribulnation.sdk.core import OverflowPolicy, PaginatedResponse
from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  FundingPayment,
  FundingRate,
  NextFunding,
  Order,
  OrderResponse,
  OrderState,
  PerpCollateral,
  PerpMarket as _PerpMarket,
  PerpPosition,
  Rules,
  Settings,
  Trade,
)

from tribulnation.bybit.core import num
from .impl import (
  CANDLE_INTERVALS,
  Category,
  MarketMixin,
  candles,
  depth_stream,
  funding_payments,
  funding_rates,
  open_orders,
  order_request,
  parse_book,
  trades_history,
  trades_stream,
)


@dataclass(kw_only=True, frozen=True)
class PerpMarket(MarketMixin, _PerpMarket):
  """One Bybit linear perpetual contract, e.g. `BTCUSDT`."""

  CANDLE_INTERVALS = CANDLE_INTERVALS

  @property
  def category(self) -> Category:
    return 'linear'

  @property
  def market_id(self) -> str:
    return self.symbol

  @property
  def exchange_id(self) -> str:
    return 'perp'

  @property
  def venue_id(self) -> str:
    return 'bybit'

  async def depth(self, *, levels: int | None = None) -> Book:
    """Fetch the market order book."""
    book = await self.call_bybit(
      lambda: self.client.market.orderbook(
        'linear', symbol=self.symbol, limit=levels, validate=self.validate
      )
    )
    return parse_book(book['b'], book['a'])

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """Subscribe to the market order book."""
    return depth_stream(self, levels=levels, queue_size=queue_size, overflow=overflow)

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Fetch the market rules.

    Args:
      refetch: Refetch the instrument catalogue instead of reading the cached one.
        The fee rate is account-scoped and always fetched fresh.
    """
    instruments = await self.perp_instruments(refetch=refetch)
    info = instruments[self.symbol]
    lot = info['lotSizeFilter']
    prices = info['priceFilter']
    fees = await self.call_bybit(
      lambda: self.client.account.fee_rate(
        'linear', symbol=self.symbol, validate=self.validate
      )
    )
    fee = fees['list'][0] if fees['list'] else None
    return Rules(
      base=info['baseCoin'],
      quote=info['quoteCoin'],
      fee_asset=info['settleCoin'],
      tick_size=prices['tickSize'],
      step_size=lot['qtyStep'],
      fixed_min_qty=lot['minOrderQty'],
      min_value=lot['minNotionalValue'],
      max_qty=lot['maxOrderQty'],
      fixed_min_price=prices['minPrice'],
      fixed_max_price=prices['maxPrice'],
      maker_fee=fee['makerFeeRate'] if fee else Decimal(0),
      taker_fee=fee['takerFeeRate'] if fee else Decimal(0),
      api=info['status'] == 'Trading',
      details=info,
    )

  def candles(
    self,
    interval: CandleInterval,
    start: datetime,
    end: datetime,
  ) -> PaginatedResponse[Candle]:
    """Fetch historical trade candles in Bybit's native page order."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(candles(self, interval, start, end))

  async def open_orders(self) -> Sequence[OrderState]:
    """Fetch your currently open orders."""
    return await open_orders(self)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Fetch your trades history."""
    return PaginatedResponse(trades_history(self, start, end))

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """Subscribe to your real-time trades."""
    return trades_stream(self, queue_size=queue_size, overflow=overflow)

  async def perp_position(self) -> PerpPosition:
    """Fetch your open position in the market."""
    positions = await self.call_bybit(
      lambda: self.client.position.list(
        'linear', symbol=self.symbol, validate=self.validate
      )
    )
    rows = positions['list']
    # A flat symbol still comes back as a full row, with `side` and every numeric
    # field an empty string.
    if not rows or not rows[0]['side']:
      return PerpPosition()
    row = rows[0]
    size = row['size']
    return PerpPosition(
      size=size if row['side'] == 'Buy' else -size,
      entry_price=num(row['avgPrice']),
    )

  async def perp_collateral(self) -> PerpCollateral:
    """Fetch the collateral bucket backing this market.

    Bybit's unified account has one margin pool shared by every derivative position,
    so this is the account-level bucket rather than a per-market one.
    """
    from .perp_exchange import PerpExchange

    exchange = PerpExchange(
      client=self.client, settings=self.settings, cache=self.cache
    )
    return await exchange.perp_collateral()

  async def available_notional(self) -> Decimal:
    """Fetch the max. notional position you can open: free collateral times leverage."""
    instruments = await self.perp_instruments()
    collateral = await self.perp_collateral()
    max_leverage = instruments[self.symbol]['leverageFilter']['maxLeverage']
    return collateral.free_collateral * max_leverage

  async def index(self, *, settings: Settings = {}) -> Decimal:
    """Fetch the market index price."""
    tickers = await self.call_bybit(
      lambda: self.client.market.tickers(
        'linear', symbol=self.symbol, validate=self.validate
      )
    )
    # `tickers()` reveals a 3-way union whatever the `category` argument was; narrow
    # it on the discriminant the three shapes share.
    assert tickers['category'] == 'linear'
    return tickers['list'][0]['indexPrice']

  async def next_funding(self) -> NextFunding:
    """Fetch the next funding rate and time."""
    tickers = await self.call_bybit(
      lambda: self.client.market.tickers(
        'linear', symbol=self.symbol, validate=self.validate
      )
    )
    assert tickers['category'] == 'linear'
    ticker = tickers['list'][0]
    rate, time = ticker['fundingRate'], ticker['nextFundingTime']
    if rate == '' or time == '0':
      # Only dated futures report these sentinels, and `market()` admits perpetuals only.
      raise ValueError(f'{self.symbol} reports no funding schedule; not a perpetual')
    instruments = await self.perp_instruments()
    return NextFunding(
      rate=rate,
      time=time,
      interval=timedelta(minutes=instruments[self.symbol]['fundingInterval']),
    )

  def funding_rates(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> PaginatedResponse[FundingRate]:
    """Fetch the market's historical funding rates."""
    return PaginatedResponse(funding_rates(self, start, end))

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    """Fetch your funding payments history."""
    return PaginatedResponse(funding_payments(self, start, end))

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Place an order in the market."""
    response = await self.call_bybit(
      lambda: self.client.trade.create_order(
        order_request('linear', self.symbol, order), validate=self.validate
      )
    )
    return OrderResponse(id=response['orderId'], details=response)

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """Cancel an order in the market."""
    return await self.call_bybit(
      lambda: self.client.trade.cancel_order(
        category='linear', symbol=self.symbol, order_id=id, validate=self.validate
      )
    )
