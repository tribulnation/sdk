"""Spot and perpetual Market objects over native Aster symbols."""

from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing_extensions import (
  Any,
  AsyncContextManager,
  AsyncIterable,
  Awaitable,
  ClassVar,
  Literal,
  Sequence,
  TypedDict,
)
from pydantic import TypeAdapter, ValidationError
from typed_aster.futures import Futures
from typed_aster.futures.trade.schemas import FuturesOrder
from typed_aster.schemas import BatchError
from typed_aster.spot import Spot
from typed_aster.spot.trade.cancel_batch_orders import SpotBatchCancelledOrder
from typed_aster.spot.trade.schemas import SpotOrder
from tribulnation.sdk.core import (
  BadRequest,
  MissingData,
  OverflowPolicy,
  PaginatedResponse,
)
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
  PerpMarket as SDKPerpMarket,
  PerpPosition,
  Position,
  Rules,
  Settings,
  Trade,
)
from tribulnation.sdk.market.types.candles import candle_windows
from ..core import Public, Scope
from .streams import connect_books, connect_trades

DepthLimit = Literal[5, 10, 20, 50, 100, 500, 1000]
DEPTH_LIMITS: tuple[DepthLimit, ...] = (5, 10, 20, 50, 100, 500, 1000)
CANDLE_PAGE = 500
BATCH_SIZE = 10
"""Native maximum orders per batch cancellation."""
ORDER_NOT_FOUND = -2013


class ErrorBody(TypedDict):
  """The native error payload of a rejected request."""

  code: int


error_body = TypeAdapter(ErrorBody)


def error_code(exc: BadRequest) -> int | None:
  """The native code of a typed-aster `BadRequest(status, payload)`, if present."""
  try:
    return error_body.validate_python(exc.args[1])['code']
  except (IndexError, ValidationError):
    return None


def order_state(row: SpotOrder | FuturesOrder) -> OrderState:
  """Map a native order with signed base quantities."""
  if 'price' not in row or 'origQty' not in row or 'executedQty' not in row:
    raise MissingData(
      'Aster order lacks its price or quantities',
      market_id=row['symbol'],
      field='price/origQty/executedQty',
    )
  sign = 1 if row['side'] == 'BUY' else -1
  return OrderState(
    id=str(row['orderId']),
    price=row['price'],
    qty=sign * row['origQty'],
    filled_qty=sign * row['executedQty'],
    active=row['status'] in ('NEW', 'PARTIALLY_FILLED'),
    details=row,
  )


@dataclass(frozen=True)
class NativeOrder:
  """An SDK order in native terms: side, absolute quantity and time in force."""

  side: Literal['BUY', 'SELL']
  quantity: Decimal
  price: Decimal | None
  """Limit price; `None` for a market order, which ignores the SDK price."""
  time_in_force: Literal['GTC', 'GTX']


def native_order(order: Order) -> NativeOrder:
  """Map MARKET, LIMIT (GTC) and POST_ONLY (GTX) orders."""
  qty = Decimal(str(order['qty']))
  if not qty.is_finite() or not qty:
    raise ValueError('Order quantity must be finite and nonzero')
  side = 'BUY' if qty > 0 else 'SELL'
  if order['type'] == 'MARKET':
    return NativeOrder(side=side, quantity=abs(qty), price=None, time_in_force='GTC')
  price = Decimal(str(order['price']))
  if not price.is_finite() or price <= 0:
    raise ValueError('Limit price must be finite and positive')
  return NativeOrder(
    side=side,
    quantity=abs(qty),
    price=price,
    time_in_force='GTX' if order['type'] == 'POST_ONLY' else 'GTC',
  )


def reject_settings(settings: Settings):
  """Aster declares no venue-specific order settings."""
  if settings:
    raise NotImplementedError('Aster does not support order settings')


@dataclass(frozen=True, kw_only=True)
class NativeMarket(Public, Market):
  """Market methods whose native requests are identical on spot and perpetuals."""

  symbol: str
  CANDLE_INTERVALS: ClassVar[frozenset[CandleInterval]] = frozenset(
    ('1m', '5m', '15m', '1h', '4h', '1d')
  )

  @property
  @abstractmethod
  def scope(self) -> Scope:
    """The native exchange this symbol trades on."""

  @property
  @abstractmethod
  def api(self) -> Spot | Futures:
    """The typed client surface of this exchange."""

  @abstractmethod
  def fetch_order(self, order_id: int) -> Awaitable[SpotOrder | FuturesOrder]:
    """Query one native order."""

  @abstractmethod
  def submit(self, order: NativeOrder) -> Awaitable[SpotOrder | FuturesOrder]:
    """Place one native order."""

  @abstractmethod
  def cancel(self, order_id: int) -> Awaitable[object]:
    """Cancel one native order."""

  @abstractmethod
  def cancel_batch(
    self, order_ids: list[int]
  ) -> Awaitable[Sequence[SpotBatchCancelledOrder | FuturesOrder | BatchError]]:
    """Cancel up to `BATCH_SIZE` native orders, one result per order."""

  @property
  def market_id(self) -> str:
    """The native symbol, e.g. `BTCUSDT`."""
    return self.symbol

  @property
  def exchange_id(self) -> str:
    """`spot` or `perp`."""
    return self.scope

  async def depth(self, *, levels: int | None = None) -> Book:
    """Read up to 1000 levels per side; quantities are in base units."""
    if levels is not None and not 1 <= levels <= DEPTH_LIMITS[-1]:
      raise ValueError(f'levels must be between 1 and {DEPTH_LIMITS[-1]}')
    limit: DepthLimit = next(
      n for n in DEPTH_LIMITS if n >= (levels or DEPTH_LIMITS[-1])
    )
    raw = await self.shared.call(
      lambda: self.api.market.depth(self.symbol, limit=limit)
    )
    book = Book(
      bids=[Book.Entry(*r) for r in raw['bids']],
      asks=[Book.Entry(*r) for r in raw['asks']],
    )
    return book if levels is None else book.limit(levels)

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """Subscribe to 20-level snapshots, trimmed per subscriber."""
    if levels is not None and not 1 <= levels <= 20:
      raise ValueError('Aster depth streams support 1-20 levels')
    return self.shared.stream(
      self.shared.books,
      (self.scope, self.symbol),
      lambda: connect_books(self.shared, self.scope, self.symbol),
      select=lambda book: book if levels is None else book.limit(levels),
      queue_size=queue_size,
      overflow=overflow,
    )

  async def fees(self, *, refetch: bool = False) -> Fees:
    """Read this account's maker and taker commission rates."""
    row = await self.shared.call(lambda: self.api.account.commission_rate(self.symbol))
    return Fees.symmetric(
      maker=row['makerCommissionRate'], taker=row['takerCommissionRate']
    )

  def candles(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> PaginatedResponse[Candle]:
    """Read trade candles in half-open `[start, end)` windows of 500."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(self.candle_pages(interval, start, end))

  async def candle_pages(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Candle]]:
    """Request each window separately, so a retry repeats only that window."""
    for lower, upper in candle_windows(start, end, interval, size=CANDLE_PAGE):
      rows = await self.shared.call(
        lambda: self.api.market.klines(
          self.symbol,
          interval=interval,
          start_time=lower,
          end_time=upper - timedelta(milliseconds=1),
          limit=CANDLE_PAGE,
        )
      )
      yield [
        Candle(
          time=r[0],
          open=r[1],
          high=r[2],
          low=r[3],
          close=r[4],
          volume=r[5],
          quote_volume=r[7],
          trades=r[8],
        )
        for r in rows
        if start <= r[0] < end
      ]

  async def query_order(self, id: str) -> OrderState | None:
    """Read an order, or `None` for the native order-not-found code."""
    try:
      row = await self.shared.call(lambda: self.fetch_order(int(id)))
    except BadRequest as exc:
      if error_code(exc) == ORDER_NOT_FOUND:
        return None
      raise
    return order_state(row)

  async def open_orders(self) -> Sequence[OrderState]:
    """Read this symbol's active orders."""
    rows = await self.shared.call(lambda: self.api.trade.open_orders(self.symbol))
    return [order_state(r) for r in rows]

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Unsupported: typed-aster 0.1.0 cannot paginate account trades."""
    raise NotImplementedError(
      'Aster trade history is not supported: typed-aster cannot paginate account trades'
    )

  def trades_stream(
    self, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """Subscribe to this symbol's fills from the account's shared stream."""
    return self.shared.stream(
      self.shared.trades,
      self.scope,
      lambda: connect_trades(self.shared, self.scope),
      select=lambda fill: fill[1] if fill[0] == self.symbol else None,
      queue_size=queue_size,
      overflow=overflow,
    )

  async def available_notional(self) -> Decimal:
    """Unsupported: Aster publishes no account-side buying capacity."""
    raise NotImplementedError('Aster publishes no account-side buying capacity')

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Place a MARKET, LIMIT (GTC) or POST_ONLY (GTX) order.

    Market orders ignore the SDK `price`.
    """
    reject_settings(settings)
    native = native_order(order)
    row = await self.shared.call(lambda: self.submit(native))
    return OrderResponse(id=str(row['orderId']), details=row)

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """Cancel one order and return the native acknowledgement."""
    reject_settings(settings)
    return await self.shared.call(lambda: self.cancel(int(id)))

  async def cancel_orders(self, ids: Sequence[str], *, settings: Settings = {}) -> Any:
    """Cancel in native batches of ten, keeping every per-order result or error."""
    reject_settings(settings)
    order_ids = [int(id) for id in ids]
    results: list[SpotBatchCancelledOrder | FuturesOrder | BatchError] = []
    for offset in range(0, len(order_ids), BATCH_SIZE):
      batch = order_ids[offset : offset + BATCH_SIZE]
      results.extend(await self.shared.call(lambda: self.cancel_batch(batch)))
    return results

  async def cancel_open_orders(self, *, settings: Settings = {}) -> Any:
    """Cancel every open order on this symbol."""
    reject_settings(settings)
    return await self.shared.call(
      lambda: self.api.trade.cancel_all_open_orders(self.symbol)
    )


@dataclass(frozen=True, kw_only=True)
class SpotMarket(NativeMarket):
  """A spot pair. Balances are unsupported, so position and collateral raise."""

  @property
  def scope(self) -> Scope:
    """The spot exchange."""
    return 'spot'

  @property
  def api(self) -> Spot:
    """The typed spot surface."""
    return self.client.spot

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Read the pair's filters; the standard fee asset is the quote asset."""
    row = (await self.shared.spot_symbols(refetch=refetch)).get(self.symbol)
    if row is None:
      raise ValueError(f'Aster spot market is not trading: {self.symbol}')
    tick = step = min_qty = max_qty = min_price = max_price = None
    rel_min = rel_max = None
    notionals: list[Decimal] = []
    for f in row['filters']:
      if f['filterType'] == 'PRICE_FILTER':
        tick, min_price, max_price = f['tickSize'], f['minPrice'], f['maxPrice']
      elif f['filterType'] == 'LOT_SIZE':
        step, min_qty, max_qty = f['stepSize'], f['minQty'], f['maxQty']
      elif f['filterType'] == 'MIN_NOTIONAL':
        notionals.append(f['minNotional'])
      elif f['filterType'] == 'NOTIONAL':
        notionals.append(f['minNotional'])
      elif f['filterType'] == 'PERCENT_PRICE':
        rel_min, rel_max = f['multiplierDown'], f['multiplierUp']
    if tick is None or step is None:
      raise MissingData(
        'Aster symbol lacks price or lot filters',
        market_id=self.symbol,
        field='filters',
      )
    return Rules(
      fee_asset=row['quoteAsset'],
      tick_size=tick,
      step_size=step,
      fixed_min_qty=min_qty or None,
      max_qty=max_qty or None,
      fixed_min_price=min_price or None,
      fixed_max_price=max_price or None,
      min_value=max(notionals) if notionals else None,
      rel_min_price=rel_min,
      rel_max_price=rel_max,
      api=True,
      details=row,
    )

  async def position(self) -> Position:
    """Unsupported: testnet account information omits funded spot balances."""
    raise NotImplementedError('Aster spot balances are not supported')

  async def collateral(self) -> Collateral:
    """Unsupported: testnet account information omits funded spot balances."""
    raise NotImplementedError('Aster spot balances are not supported')

  def fetch_order(self, order_id: int):
    """Query one spot order."""
    return self.api.trade.order(symbol=self.symbol, order_id=order_id)

  def submit(self, order: NativeOrder):
    """Place one spot order."""
    if order.price is None:
      return self.api.trade.place_order(
        {
          'symbol': self.symbol,
          'side': order.side,
          'type': 'MARKET',
          'quantity': order.quantity,
        }
      )
    return self.api.trade.place_order(
      {
        'symbol': self.symbol,
        'side': order.side,
        'type': 'LIMIT',
        'quantity': order.quantity,
        'price': order.price,
        'timeInForce': order.time_in_force,
      }
    )

  def cancel(self, order_id: int):
    """Cancel one spot order."""
    return self.api.trade.cancel_order(symbol=self.symbol, order_id=order_id)

  def cancel_batch(self, order_ids: list[int]):
    """Cancel up to ten spot orders."""
    return self.api.trade.cancel_batch_orders(self.symbol, order_id_list=order_ids)


@dataclass(frozen=True, kw_only=True)
class PerpMarket(NativeMarket, SDKPerpMarket):
  """A linear perpetual, supporting one-way positions and cross margin."""

  @property
  def scope(self) -> Scope:
    """The perpetual exchange."""
    return 'perp'

  @property
  def api(self) -> Futures:
    """The typed futures surface."""
    return self.client.futures

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Read the contract's filters; the standard fee asset is the margin asset."""
    row = (await self.shared.perp_symbols(refetch=refetch)).get(self.symbol)
    if row is None:
      raise ValueError(f'Aster perpetual is not trading: {self.symbol}')
    tick = step = min_qty = max_qty = min_price = max_price = None
    min_value = rel_min = rel_max = None
    for f in row['filters']:
      if f['filterType'] == 'PRICE_FILTER':
        tick, min_price, max_price = f['tickSize'], f['minPrice'], f['maxPrice']
      elif f['filterType'] == 'LOT_SIZE':
        step, min_qty, max_qty = f['stepSize'], f['minQty'], f['maxQty']
      elif f['filterType'] == 'MIN_NOTIONAL':
        min_value = f['notional']
      elif f['filterType'] == 'PERCENT_PRICE':
        rel_min, rel_max = f['multiplierDown'], f['multiplierUp']
    if tick is None or step is None:
      raise MissingData(
        'Aster contract lacks price or lot filters',
        market_id=self.symbol,
        field='filters',
      )
    return Rules(
      fee_asset=row['marginAsset'],
      tick_size=tick,
      step_size=step,
      fixed_min_qty=min_qty or None,
      max_qty=max_qty or None,
      fixed_min_price=min_price or None,
      fixed_max_price=max_price or None,
      min_value=min_value,
      rel_min_price=rel_min,
      rel_max_price=rel_max,
      api=True,
      details=row,
    )

  async def index(self, *, settings: Settings = {}) -> Decimal:
    """Read the published index price."""
    rows = await self.shared.call(lambda: self.api.market.premium_index(self.symbol))
    for row in rows if isinstance(rows, list) else [rows]:
      if row['symbol'] == self.symbol:
        return row['indexPrice']
    raise MissingData(
      'Aster premium index omits the symbol', market_id=self.symbol, field='indexPrice'
    )

  async def next_funding(self) -> NextFunding:
    """Read the predicted rate, settlement time and the symbol's own interval."""
    rows = await self.shared.call(lambda: self.api.market.premium_index(self.symbol))
    premium = next(
      (
        r
        for r in (rows if isinstance(rows, list) else [rows])
        if r['symbol'] == self.symbol
      ),
      None,
    )
    configs = await self.shared.call(lambda: self.api.market.funding_info(self.symbol))
    config = next((r for r in configs if r['symbol'] == self.symbol), None)
    if premium is None or config is None:
      raise MissingData(
        'Aster funding data omits the symbol', market_id=self.symbol, field='funding'
      )
    if (hours := config['fundingIntervalHours']) is None:
      raise MissingData(
        'Aster funding configuration has no interval',
        market_id=self.symbol,
        field='fundingIntervalHours',
      )
    return NextFunding(
      rate=premium['lastFundingRate'],
      time=premium['nextFundingTime'],
      interval=timedelta(hours=hours),
    )

  def funding_rates(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> PaginatedResponse[FundingRate]:
    """Read settled funding rates; each native page is retried on its own."""
    return PaginatedResponse(self.funding_rate_pages(start, end))

  async def funding_rate_pages(
    self, start: datetime | None, end: datetime | None
  ) -> AsyncIterable[Sequence[FundingRate]]:
    """Map the typed funding-rate pager through the SDK request seam."""
    pages = self.api.market.funding_rate_paged(
      self.symbol, start_time=start, end_time=end, limit=1000
    )
    async for page in pages.via(self.shared.call):
      yield [FundingRate(rate=r['fundingRate'], time=r['fundingTime']) for r in page]

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    """Unsupported until a nonzero native payment has been verified."""
    raise NotImplementedError('Aster funding payments are not supported yet')

  async def one_way_position(self):
    """Read the symbol's single one-way (`BOTH`) position row."""
    rows = await self.shared.call(lambda: self.api.position.risk(self.symbol))
    if len(rows) != 1 or rows[0]['positionSide'] != 'BOTH':
      raise NotImplementedError('Aster hedge-mode positions are not supported')
    return rows[0]

  async def perp_position(self) -> PerpPosition:
    """Read the signed one-way size and entry price."""
    row = await self.one_way_position()
    return PerpPosition(size=row['positionAmt'], entry_price=row['entryPrice'])

  async def collateral(self) -> Collateral:
    """Read equity and free collateral of the cross-margin bucket."""
    row = await self.one_way_position()
    if row['marginType'] != 'cross':
      raise NotImplementedError('Aster isolated-margin collateral is not supported')
    return await self.shared.cross_collateral()

  async def perp_collateral(self) -> PerpCollateral:
    """Unsupported: Aster publishes configured, not actual, leverage."""
    raise NotImplementedError('Aster does not publish actual account leverage')

  def fetch_order(self, order_id: int):
    """Query one perpetual order."""
    return self.api.trade.order({'symbol': self.symbol, 'orderId': order_id})

  def submit(self, order: NativeOrder):
    """Place one perpetual order, returning its final state."""
    if order.price is None:
      return self.api.trade.place_order(
        {
          'symbol': self.symbol,
          'side': order.side,
          'type': 'MARKET',
          'quantity': order.quantity,
          'newOrderRespType': 'RESULT',
        }
      )
    return self.api.trade.place_order(
      {
        'symbol': self.symbol,
        'side': order.side,
        'type': 'LIMIT',
        'quantity': order.quantity,
        'price': order.price,
        'timeInForce': order.time_in_force,
        'newOrderRespType': 'RESULT',
      }
    )

  def cancel(self, order_id: int):
    """Cancel one perpetual order."""
    return self.api.trade.cancel_order({'symbol': self.symbol, 'orderId': order_id})

  def cancel_batch(self, order_ids: list[int]):
    """Cancel up to ten perpetual orders."""
    return self.api.trade.cancel_batch_orders(
      {'symbol': self.symbol, 'orderIdList': order_ids}
    )
