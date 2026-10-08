"""Spot and perpetual Market objects over native Aster symbols."""

from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import secrets
from typing_extensions import (
  Any,
  AsyncContextManager,
  AsyncIterable,
  Awaitable,
  ClassVar,
  Iterable,
  Literal,
  Sequence,
  TypedDict,
)
from pydantic import TypeAdapter, ValidationError
from typed_aster.futures import Futures
from typed_aster.futures.account.schemas import FuturesAccount, FuturesAccountPosition
from typed_aster.futures.position.risk import PositionRisk
from typed_aster.futures.trade.place_order import Request as FuturesOrderRequest
from typed_aster.futures.trade.schemas import FuturesOrder
from typed_aster.futures.trade.user_trades import AccountTradeItem
from typed_aster.schemas import AccountInfo, AccountTrade, BatchError
from typed_aster.spot import Spot
from typed_aster.spot.market.exchange_info import SpotSymbol
from typed_aster.spot.trade.cancel_batch_orders import SpotBatchCancelledOrder
from typed_aster.spot.trade.place_order import Request as SpotOrderRequest
from typed_aster.spot.trade.schemas import SpotOrder
from tribulnation.sdk.core import (
  ApiError,
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
  ExchangeTrade,
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
from ..core import Public, Scope, Shared
from .streams import book_time, connect_books, connect_trades

DepthLimit = Literal[5, 10, 20, 50, 100, 500, 1000]
DEPTH_LIMITS: tuple[DepthLimit, ...] = (5, 10, 20, 50, 100, 500, 1000)
CANDLE_PAGE = 500
BATCH_SIZE = 10
"""Native maximum orders per batch cancellation."""
ORDER_NOT_FOUND = -2013
TRADES_WINDOW = timedelta(days=7)
"""Widest `userTrades` time window; a wider one is refused with `-4165`."""
TRADES_PAGE = 1000
NO_OPEN_INTEREST_CAP = Decimal(-1)
"""`remainingOpenableNotionalValue` when the symbol has no open-interest cap."""


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


def parse_trade(row: AccountTradeItem | AccountTrade) -> Trade:
  """Map one spot or perpetual account trade with a signed base quantity.

  The fee keeps the fill's own `commissionAsset`: spot fills pay in the asset they
  deliver, so it differs between buys and sells.

  Raises:
    MissingData: The row lacks its side or maker flag, or has a fee amount without
      its asset (or vice versa). An incomplete trade is never emitted.
  """
  if 'side' not in row or 'maker' not in row:
    raise MissingData(
      'Aster trade lacks its side or maker flag',
      market_id=row['symbol'],
      field='side/maker',
    )
  fee = None
  if 'commission' in row and 'commissionAsset' in row:
    fee = Trade.Fee(amount=row['commission'], asset=row['commissionAsset'])
  elif 'commission' in row or 'commissionAsset' in row:
    raise MissingData(
      'Aster trade has an incomplete commission',
      market_id=row['symbol'],
      field='commission/commissionAsset',
    )
  return Trade(
    id=str(row['id']),
    order_id=str(row['orderId']),
    price=row['price'],
    qty=row['qty'] if row['side'] == 'BUY' else -row['qty'],
    time=row['time'],
    maker=row['maker'],
    fee=fee,
    details=row,
  )


def exchange_trade(row: AccountTradeItem | AccountTrade) -> ExchangeTrade:
  """Map one account trade, keeping its native symbol as the market ID."""
  return ExchangeTrade(**vars(parse_trade(row)), market_id=row['symbol'])


def trade_windows(
  start: datetime, end: datetime, now: datetime
) -> Iterable[tuple[datetime, datetime]]:
  """Inclusive `userTrades` windows of at most seven days covering `[start, end]`.

  The venue refuses a future `startTime` and an `endTime` well ahead of now, so the
  walk stops at `now`.
  """
  horizon = min(end, now)
  lower = start
  while lower <= horizon:
    upper = min(lower + TRADES_WINDOW, horizon)
    yield lower, upper
    lower = upper + timedelta(milliseconds=1)


async def spot_trade_rows(
  shared: Shared, lower: datetime, upper: datetime
) -> AsyncIterable[Sequence[AccountTrade]]:
  """Every spot fill of the account within inclusive `[lower, upper]`, any symbol.

  Without a symbol, the order of `fromId` across symbols is unverified, so a window
  that fills a page is halved and requested again instead of walked by ID. Each
  request is retried on its own.

  Raises:
    ApiError: A single millisecond holds a full page, which halving cannot split.
  """
  pending = [(lower, upper)]
  while pending:
    lo, hi = pending.pop()
    rows = await shared.call(
      lambda: shared.client.spot.trade.user_trades(
        start_time=lo, end_time=hi, limit=TRADES_PAGE
      )
    )
    if len(rows) < TRADES_PAGE:
      if rows:
        yield rows
      continue
    if hi - lo < timedelta(milliseconds=1):
      raise ApiError('Aster spot fills fill a page within one millisecond')
    middle = lo + (hi - lo) / 2
    middle = middle.replace(microsecond=middle.microsecond // 1000 * 1000)
    pending.append((middle + timedelta(milliseconds=1), hi))
    pending.append((lo, middle))


def spot_balance(info: AccountInfo, asset: str) -> tuple[Decimal, Decimal]:
  """The free and locked amounts of one spot asset; an unlisted asset holds zero."""
  for row in info['balances']:
    if row['asset'] == asset:
      return row['free'], row['locked']
  return Decimal(0), Decimal(0)


def one_way_row(
  positions: Sequence[FuturesAccountPosition], symbol: str
) -> FuturesAccountPosition:
  """The symbol's single one-way (`BOTH`) row of the futures account.

  Raises:
    NotImplementedError: The symbol has hedge-mode (`LONG`/`SHORT`) rows.
    MissingData: The account lists no row for the symbol.
  """
  rows = [p for p in positions if p['symbol'] == symbol]
  if any(p['positionSide'] != 'BOTH' for p in rows):
    raise NotImplementedError('Aster hedge-mode positions are not supported')
  if len(rows) != 1:
    raise MissingData(
      'Aster account information omits the symbol', market_id=symbol, field='positions'
    )
  return rows[0]


def isolated_equity(row: FuturesAccountPosition) -> Decimal:
  """An isolated position's own margin: its isolated wallet plus unrealized PnL."""
  return row['isolatedWallet'] + row['unrealizedProfit']


def notional_leverage(notional: Decimal, equity: Decimal) -> Decimal:
  """Position notional over equity; zero when the bucket has no positive equity."""
  return notional / equity if equity > 0 else Decimal(0)


def cross_collateral(account: FuturesAccount) -> PerpCollateral:
  """The cross-margin bucket from the join-margin account view.

  The account totals value every margin asset in USDT (Multi-Assets mode included).
  Isolated positions' own margin, initial and maintenance requirements are taken out
  of them, and leverage counts only cross positions' notional. Free collateral is the
  account's `availableBalance`.
  """
  isolated = [p for p in account['positions'] if p['isolated']]
  equity = account['totalMarginBalance'] - sum(
    (isolated_equity(p) for p in isolated), Decimal(0)
  )
  notional = sum(
    (abs(p['notional']) for p in account['positions'] if not p['isolated']),
    Decimal(0),
  )
  return PerpCollateral(
    equity=equity,
    free_collateral=account['availableBalance'],
    initial_margin=account['totalInitialMargin']
    - sum((p['initialMargin'] for p in isolated), Decimal(0)),
    maintenance_margin=account['totalMaintMargin']
    - sum((p['maintMargin'] for p in isolated), Decimal(0)),
    leverage=notional_leverage(notional, equity),
    margin_mode='cross',
  )


def isolated_collateral(row: FuturesAccountPosition) -> PerpCollateral:
  """One isolated position's own bucket; margin above its initial margin is free."""
  equity = isolated_equity(row)
  return PerpCollateral(
    equity=equity,
    free_collateral=max(equity - row['initialMargin'], Decimal(0)),
    initial_margin=row['initialMargin'],
    maintenance_margin=row['maintMargin'],
    leverage=notional_leverage(abs(row['notional']), equity),
    margin_mode='isolated',
  )


@dataclass(frozen=True)
class NativeOrder:
  """An SDK order in native terms: side, absolute quantity and time in force."""

  side: Literal['BUY', 'SELL']
  quantity: Decimal
  price: Decimal | None
  """Limit price; `None` for a market order, which ignores the SDK price."""
  time_in_force: Literal['GTC', 'GTX']
  client_order_id: str | None = None
  """Sent as `newClientOrderId`; the venue generates one when `None`."""


def plain_decimal(x: Decimal) -> Decimal:
  """Write `x` in positional form without fractional trailing zeros, as the venue parses it.

  `Decimal.normalize()`, which the SDK's tick and step rounding applies, turns round
  numbers into exponent form (`190` into `1.9E+2`). typed-aster sends a request decimal
  as its `str()`, and the venue rejects exponent form with -1102 ("Mandatory parameter
  'quantity' was not sent, was empty/null, or malformed").
  """
  return Decimal(f'{x.normalize():f}')


def position_leverage(rows: Sequence[PositionRisk], symbol: str) -> Decimal:
  """The symbol's initial leverage from its `positionRisk` rows.

  Leverage is a per-symbol setting, so hedge-mode `LONG`/`SHORT` rows repeat it; the
  lowest is used should they ever differ. Flat symbols are listed too, so a missing
  row is a malformed response rather than an unconfigured symbol.

  Raises:
    MissingData: No row reports a positive leverage for the symbol.
  """
  values = [r['leverage'] for r in rows if r['symbol'] == symbol and r['leverage'] > 0]
  if not values:
    raise MissingData(
      'Aster position risk omits the symbol', market_id=symbol, field='leverage'
    )
  return Decimal(min(values))


def native_order(order: Order) -> NativeOrder:
  """Map MARKET, LIMIT (GTC) and POST_ONLY (GTX) orders."""
  qty = Decimal(str(order['qty']))
  if not qty.is_finite() or not qty:
    raise ValueError('Order quantity must be finite and nonzero')
  side = 'BUY' if qty > 0 else 'SELL'
  quantity = plain_decimal(abs(qty))
  client_order_id = order.get('client_order_id')
  if order['type'] == 'MARKET':
    return NativeOrder(
      side=side,
      quantity=quantity,
      price=None,
      time_in_force='GTC',
      client_order_id=client_order_id,
    )
  price = Decimal(str(order['price']))
  if not price.is_finite() or price <= 0:
    raise ValueError('Limit price must be finite and positive')
  return NativeOrder(
    side=side,
    quantity=quantity,
    price=plain_decimal(price),
    time_in_force='GTX' if order['type'] == 'POST_ONLY' else 'GTC',
    client_order_id=client_order_id,
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

  async def depth(self, *, levels: int | None = None, settings: Settings = {}) -> Book:
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
      time=book_time(raw),
    )
    return book if levels is None else book.limit(levels)

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
    settings: Settings = {},
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
    """Read this account's maker and taker commission rates; needs `user` and `signer`.

    The quoted rates apply to buys and sells alike and exclude any optional
    fee-payment discount (ADR 0002).
    """
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

  def random_client_order_id(self) -> str:
    """Generate 128 random bits as 32 hex digits, within `newClientOrderId`'s 36 characters."""
    return secrets.token_hex(16)

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
  """A spot pair. Balances and fills are mainnet-only: testnet omits them."""

  @property
  def scope(self) -> Scope:
    """The spot exchange."""
    return 'spot'

  @property
  def api(self) -> Spot:
    """The typed spot surface."""
    return self.client.spot

  async def symbol_info(self, *, refetch: bool = False) -> SpotSymbol:
    """The pair's cached exchange information."""
    row = (await self.shared.spot_symbols(refetch=refetch)).get(self.symbol)
    if row is None:
      raise ValueError(f'Aster spot market is not trading: {self.symbol}')
    return row

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Read the pair's filters. The fee asset depends on the fill (ADR 0028).

    A spot fill pays its fee in the asset it delivers: the base asset on a buy and the
    quote asset on a sell. `Trade.fee.asset` names it per fill.
    """
    row = await self.symbol_info(refetch=refetch)
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
      fee_asset=None,
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

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Read this pair's fills within inclusive `[start, end]` bounds, up to now.

    Mainnet only: testnet `userTrades` omits confirmed buy fills.
    """
    if start.tzinfo is None or end.tzinfo is None:
      raise ValueError('Trade history bounds must be timezone-aware')
    if not self.shared.mainnet:
      raise NotImplementedError(
        'Aster testnet spot trade history is not supported: userTrades omits buy fills'
      )
    return PaginatedResponse(self.trade_pages(start, end))

  async def trade_pages(
    self, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Trade]]:
    """Walk seven-day windows with the typed `fromId` pager, retrying each page."""
    for lower, upper in trade_windows(start, end, datetime.now(timezone.utc)):
      pages = self.api.trade.user_trades_paged(
        self.symbol, start_time=lower, end_time=upper, limit=TRADES_PAGE
      )
      async for rows in pages.via(self.shared.call):
        if page := [parse_trade(r) for r in rows if start <= r['time'] <= end]:
          yield page

  async def balances(self) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Free and locked base, then free and locked quote balances.

    Raises:
      NotImplementedError: On testnet, whose account information omits funded
        balances.
    """
    if not self.shared.mainnet:
      raise NotImplementedError(
        'Aster testnet spot balances are not supported: account information omits them'
      )
    row = await self.symbol_info()
    info = await self.shared.call(self.api.account.info)
    return (
      *spot_balance(info, row['baseAsset']),
      *spot_balance(info, row['quoteAsset']),
    )

  async def position(self) -> Position:
    """The base asset held, free plus locked in open orders."""
    free, locked, _, _ = await self.balances()
    return Position(size=free + locked)

  async def collateral(self) -> Collateral:
    """The quote asset: equity is free plus locked, free collateral the free part."""
    _, _, free, locked = await self.balances()
    return Collateral(equity=free + locked, free_collateral=free)

  def fetch_order(self, order_id: int):
    """Query one spot order."""
    return self.api.trade.order(symbol=self.symbol, order_id=order_id)

  def submit(self, order: NativeOrder):
    """Place one spot order."""
    request: SpotOrderRequest
    if order.price is None:
      request = {
        'symbol': self.symbol,
        'side': order.side,
        'type': 'MARKET',
        'quantity': order.quantity,
      }
    else:
      request = {
        'symbol': self.symbol,
        'side': order.side,
        'type': 'LIMIT',
        'quantity': order.quantity,
        'price': order.price,
        'timeInForce': order.time_in_force,
      }
    if order.client_order_id is not None:
      request['newClientOrderId'] = order.client_order_id
    return self.api.trade.place_order(request)

  def cancel(self, order_id: int):
    """Cancel one spot order."""
    return self.api.trade.cancel_order(symbol=self.symbol, order_id=order_id)

  def cancel_batch(self, order_ids: list[int]):
    """Cancel up to ten spot orders."""
    return self.api.trade.cancel_batch_orders(self.symbol, order_id_list=order_ids)


@dataclass(frozen=True, kw_only=True)
class PerpMarket(NativeMarket, SDKPerpMarket):
  """A linear perpetual: one-way positions, in cross or isolated margin."""

  @property
  def scope(self) -> Scope:
    """The perpetual exchange."""
    return 'perp'

  @property
  def api(self) -> Futures:
    """The typed futures surface."""
    return self.client.futures

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Read the contract's filters. The fee asset depends on the fill (ADR 0028).

    With the account's futures `feeBurn` setting on, fees are paid in ASTER while the
    futures wallet holds it, and in the margin asset otherwise; with it off, in the
    margin asset. Rules read no account settings (ADR 0001, 0002), so no single asset
    is claimed: `Trade.fee.asset` names it per fill.
    """
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
      fee_asset=None,
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

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Read this symbol's fills within inclusive `[start, end]` bounds.

    The venue refuses a future `startTime` (`-4181`) and an `endTime` more than
    about a day ahead (`-4165`), so the walk stops at the current time.
    """
    if start.tzinfo is None or end.tzinfo is None:
      raise ValueError('Trade history bounds must be timezone-aware')
    return PaginatedResponse(self.trade_pages(start, end))

  async def trade_pages(
    self, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Trade]]:
    """Walk seven-day windows with the typed `fromId` pager, retrying each page."""
    for lower, upper in trade_windows(start, end, datetime.now(timezone.utc)):
      pages = self.api.trade.user_trades_paged(
        self.symbol, start_time=lower, end_time=upper, limit=TRADES_PAGE
      )
      async for rows in pages.via(self.shared.call):
        if page := [parse_trade(r) for r in rows if start <= r['time'] <= end]:
          yield page

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    """Read settled funding cashflows, positive when received."""
    if start.tzinfo is None or end.tzinfo is None:
      raise ValueError('Funding history bounds must be timezone-aware')
    return PaginatedResponse(self.funding_payment_pages(start, end))

  async def funding_payment_pages(
    self, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[FundingPayment]]:
    """Page native funding income through the retryable request seam."""
    pages = self.api.account.income_paged(
      self.symbol, income_type='FUNDING_FEE', start_time=start, end_time=end, limit=1000
    )
    async for page in pages.via(self.shared.call):
      yield [FundingPayment(amount=r['income'], time=r['time']) for r in page]

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

  async def leverage(self, *, refetch: bool = False) -> Decimal:
    """The symbol's configured initial leverage (`positionRisk`), cached per symbol.

    The setting applies to cross and isolated margin alike.
    """
    cached = self.shared.leverages.get(self.symbol)
    if cached is not None and not refetch:
      return cached
    rows = await self.shared.call(lambda: self.api.position.risk(self.symbol))
    leverage = position_leverage(rows, self.symbol)
    self.shared.leverages[self.symbol] = leverage
    return leverage

  async def perp_collateral(self) -> PerpCollateral:
    """The bucket backing this one-way position: cross, or its own isolated margin.

    Both come from the join-margin account view; see `cross_collateral` and
    `isolated_collateral`. Leverage is the used leverage, notional over equity.

    Raises:
      NotImplementedError: The symbol is in hedge mode.
    """
    account = await self.shared.futures_account()
    row = one_way_row(account['positions'], self.symbol)
    return isolated_collateral(row) if row['isolated'] else cross_collateral(account)

  async def available_notional(self) -> Decimal:
    """The free cross balance times `leverage()`, capped by the venue's notional caps.

    New margin comes from the account's `availableBalance` in either margin mode, so
    isolated positions are sized against it too. Two venue caps also apply: the room
    left in the leverage bracket (`maxNotional` at the current leverage, less the
    position's own notional) and the symbol's remaining open-interest allowance at that
    leverage (`remainingOpenableNotionalValue`, uncapped at `-1`). Reducing or
    reversing a position is not modelled: the result is the same-direction room
    (ADR 0041).
    """
    leverage = await self.leverage()
    account = await self.shared.futures_account()
    row = one_way_row(account['positions'], self.symbol)
    remaining = await self.shared.call(
      lambda: self.api.market.remaining_openable_notional_value(
        self.symbol, leverage=int(leverage)
      )
    )
    caps = [
      account['availableBalance'] * leverage,
      row['maxNotional'] - abs(row['notional']),
    ]
    if (cap := remaining['remainingOpenableNotionalValue']) != NO_OPEN_INTEREST_CAP:
      caps.append(cap)
    return max(min(caps), Decimal(0))

  def fetch_order(self, order_id: int):
    """Query one perpetual order."""
    return self.api.trade.order({'symbol': self.symbol, 'orderId': order_id})

  def submit(self, order: NativeOrder):
    """Place one perpetual order, returning its final state."""
    request: FuturesOrderRequest
    if order.price is None:
      request = {
        'symbol': self.symbol,
        'side': order.side,
        'type': 'MARKET',
        'quantity': order.quantity,
        'newOrderRespType': 'RESULT',
      }
    else:
      request = {
        'symbol': self.symbol,
        'side': order.side,
        'type': 'LIMIT',
        'quantity': order.quantity,
        'price': order.price,
        'timeInForce': order.time_in_force,
        'newOrderRespType': 'RESULT',
      }
    if order.client_order_id is not None:
      request['newClientOrderId'] = order.client_order_id
    return self.api.trade.place_order(request)

  def cancel(self, order_id: int):
    """Cancel one perpetual order."""
    return self.api.trade.cancel_order({'symbol': self.symbol, 'orderId': order_id})

  def cancel_batch(self, order_ids: list[int]):
    """Cancel up to ten perpetual orders."""
    return self.api.trade.cancel_batch_orders(
      {'symbol': self.symbol, 'orderIdList': order_ids}
    )
