"""Bybit's spot market (`category='spot'`)."""

from typing_extensions import Any, AsyncContextManager, AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.core import OverflowPolicy, PaginatedResponse
from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  Collateral,
  Market,
  Order,
  OrderResponse,
  OrderState,
  Position,
  Rules,
  Fees,
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
  open_orders,
  order_request,
  parse_book,
  trades_history,
  trades_stream,
)


@dataclass(kw_only=True, frozen=True)
class SpotMarket(MarketMixin, Market):
  """One Bybit spot pair, e.g. `BTCUSDT`."""

  CANDLE_INTERVALS = CANDLE_INTERVALS

  @property
  def category(self) -> Category:
    return 'spot'

  @property
  def market_id(self) -> str:
    return self.symbol

  @property
  def exchange_id(self) -> str:
    return 'spot'

  @property
  def venue_id(self) -> str:
    return 'bybit'

  async def depth(self, *, levels: int | None = None) -> Book:
    """Fetch the market order book."""
    book = await self.call_bybit(
      lambda: self.client.market.orderbook(
        'spot', symbol=self.symbol, limit=levels, validate=self.validate
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
        Standard fees are unknown here; use fees() for account rates.
    """
    instruments = await self.spot_instruments(refetch=refetch)
    info = instruments[self.symbol]
    lot = info['lotSizeFilter']
    return Rules(
      fee_asset=info['quoteCoin'],
      tick_size=info['priceFilter']['tickSize'],
      step_size=lot['basePrecision'],
      fixed_min_qty=lot['minOrderQty'],
      min_value=lot['minOrderAmt'],
      max_qty=lot['maxOrderQty'],
      fees=None,
      api=info['status'] == 'Trading',
      details=info,
    )

  async def fees(self, *, refetch: bool = False) -> Fees:
    """Read the exact symbol's account rates; never select an unrelated row."""
    response = await self.call_bybit(
      lambda: self.client.account.fee_rate(
        'spot', symbol=self.symbol, validate=self.validate
      )
    )
    rows = [row for row in response['list'] if row['symbol'] == self.symbol]
    if len(rows) != 1:
      raise ValueError('Bybit account fee response must contain the requested symbol')
    return Fees.symmetric(maker=rows[0]['makerFeeRate'], taker=rows[0]['takerFeeRate'])

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

  async def position(self) -> Position:
    """Fetch your base-asset balance in the market."""
    instruments = await self.spot_instruments()
    balance = await self.coin_balance(instruments[self.symbol]['baseCoin'])
    return Position(size=num(balance['walletBalance']) if balance else Decimal(0))

  async def collateral(self) -> Collateral:
    """Fetch the quote-asset balance backing this market."""
    instruments = await self.spot_instruments()
    balance = await self.coin_balance(instruments[self.symbol]['quoteCoin'])
    if balance is None:
      return Collateral(equity=Decimal(0), free_collateral=Decimal(0))
    equity = num(balance['walletBalance'])
    locked = num(balance.get('locked'))
    return Collateral(equity=equity, free_collateral=equity - locked)

  async def available_notional(self) -> Decimal:
    """Fetch the free quote-asset balance."""
    return (await self.collateral()).free_collateral

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Place an order in the market."""
    response = await self.call_bybit(
      lambda: self.client.trade.create_order(
        order_request('spot', self.symbol, order), validate=self.validate
      )
    )
    return OrderResponse(id=response['orderId'], details=response)

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """Cancel an order in the market."""
    return await self.call_bybit(
      lambda: self.client.trade.cancel_order(
        category='spot', symbol=self.symbol, order_id=id, validate=self.validate
      )
    )
