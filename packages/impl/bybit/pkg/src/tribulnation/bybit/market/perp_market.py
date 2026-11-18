"""Bybit's linear (USDT/USDC-margined) perpetual market (`category='linear'`)."""

from typing_extensions import Any, AsyncContextManager, AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import secrets

from typed_bybit import ApiError as ClientApiError
from typed_bybit.position.list import Position

from tribulnation.sdk.core import MissingData, OverflowPolicy, PaginatedResponse
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
  funding_payments,
  funding_rates,
  open_orders,
  order_request,
  parse_book,
  trades_history,
  trades_stream,
)

LEVERAGE_NOT_MODIFIED = 110043
"""`retCode` for a set-leverage request that names the leverage already set."""


def position_leverage(rows: Sequence[Position], symbol: str) -> Decimal:
  """The symbol's leverage setting from its `/v5/position/list` rows.

  A symbol-scoped request lists the symbol even when flat, with its setting. Hedge
  mode lists a long and a short row; the lowest is used should they differ.

  Raises:
    MissingData: The response lists no row for the symbol.
    NotImplementedError: The rows carry no leverage, as under portfolio margin,
      where Bybit applies no per-symbol leverage.
  """
  rows = [r for r in rows if r['symbol'] == symbol]
  if not rows:
    raise MissingData(
      'Bybit position list omits the symbol', market_id=symbol, field='leverage'
    )
  values = [Decimal(r['leverage']) for r in rows if r['leverage']]
  if not values:
    raise NotImplementedError(
      f'Bybit reports no leverage for {symbol}; portfolio margin has none per symbol'
    )
  return min(values)


def leverage_request(leverage: Decimal, step: Decimal) -> str:
  """`leverage` as the plain decimal string Bybit accepts, on the symbol's step.

  Args:
    leverage: The multiple to set.
    step: The symbol's `leverageFilter.leverageStep`.

  Raises:
    ValueError: `leverage` is not positive or not a multiple of `step`.
  """
  if leverage <= 0 or leverage % step != 0:
    raise ValueError(f'Leverage must be a positive multiple of {step}, got {leverage}')
  return f'{leverage.normalize():f}'


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

  async def depth(self, *, levels: int | None = None, settings: Settings = {}) -> Book:
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
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """Subscribe to the market order book."""
    return depth_stream(self, levels=levels, queue_size=queue_size, overflow=overflow)

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Fetch the market rules.

    Args:
      refetch: Refetch the instrument catalogue instead of reading the cached one.
        Standard fees are unknown here; use fees() for account rates.
    """
    instruments = await self.perp_instruments(refetch=refetch)
    info = instruments[self.symbol]
    lot = info['lotSizeFilter']
    prices = info['priceFilter']
    return Rules(
      fee_asset=info['settleCoin'],
      tick_size=prices['tickSize'],
      step_size=lot['qtyStep'],
      fixed_min_qty=lot['minOrderQty'],
      min_value=lot['minNotionalValue'],
      max_qty=lot['maxOrderQty'],
      fixed_min_price=prices['minPrice'],
      fixed_max_price=prices['maxPrice'],
      fees=None,
      api=info['status'] == 'Trading',
      details=info,
    )

  async def fees(self, *, refetch: bool = False) -> Fees:
    """Read the exact symbol's account rates; never select an unrelated row."""
    response = await self.call_bybit(
      lambda: self.client.account.fee_rate(
        'linear', symbol=self.symbol, validate=self.validate
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
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """Subscribe to your real-time trades."""
    return trades_stream(self, queue_size=queue_size, overflow=overflow)

  async def perp_position(self, *, ttl: timedelta | None = None) -> PerpPosition:
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

  async def perp_collateral(self, *, ttl: timedelta | None = None) -> PerpCollateral:
    """Fetch the collateral bucket backing this market.

    Bybit's unified account has one margin pool shared by every derivative position,
    so this is the account-level bucket rather than a per-market one.
    """
    from .perp_exchange import PerpExchange

    exchange = PerpExchange(
      client=self.client, settings=self.settings, cache=self.cache
    )
    return await exchange.perp_collateral()

  async def leverage(self, *, ttl: timedelta | None = None) -> Decimal:
    """The symbol's leverage setting, from `/v5/position/list`.

    Bybit lists the account's setting for every symbol, its default where never
    configured, so this never raises `LeverageNotSet`. Reads are not shared: `ttl`
    is accepted and every call asks the venue.
    """
    positions = await self.call_bybit(
      lambda: self.client.position.list(
        'linear', symbol=self.symbol, validate=self.validate
      )
    )
    return position_leverage(positions['list'], self.symbol)

  async def set_leverage(self, leverage: Decimal):
    """Set the symbol's leverage (`POST /v5/position/set-leverage`).

    Buy and sell leverage are set alike, as one-way mode and cross margin require.
    The request takes no margin mode and leaves the account-wide one alone. Decimal
    values are accepted on the symbol's `leverageStep`; the range is the venue's to
    refuse. Setting the leverage already set (`retCode` 110043) succeeds.

    Raises:
      ValueError: `leverage` is not positive or not on the symbol's leverage step.
    """
    instruments = await self.perp_instruments()
    step = instruments[self.symbol]['leverageFilter']['leverageStep']
    value = leverage_request(leverage, step)

    async def send():
      """Send the request, treating Bybit's 'leverage not modified' as success."""
      try:
        await self.client.position.set_leverage(
          'linear',
          symbol=self.symbol,
          buy_leverage=value,
          sell_leverage=value,
          validate=self.validate,
        )
      except ClientApiError as e:
        if not e.args or e.args[0] != LEVERAGE_NOT_MODIFIED:
          raise

    await self.call_bybit(send)

  async def available_notional(self, *, ttl: timedelta | None = None) -> Decimal:
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

  async def next_funding(self, *, ttl: timedelta | None = None) -> NextFunding:
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

  def random_client_order_id(self) -> str:
    """Generate 128 random bits as 32 hex digits, within `orderLinkId`'s 36 characters."""
    return secrets.token_hex(16)

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
