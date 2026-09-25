"""Aster perp mappings promoted from the executed testnet PoC."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing_extensions import (
  Any,
  AsyncIterable,
  Collection,
  Mapping,
  Sequence,
  TypedDict,
  overload,
)
from dataclasses import dataclass
from pydantic import TypeAdapter
from tribulnation.sdk.core import BadRequest, PaginatedResponse
from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  Collateral,
  Fees,
  ExchangeFundingPayment,
  ExchangeTrade,
  FundingPayment,
  FundingRate,
  NextFunding,
  Order,
  OrderResponse,
  OrderState,
  PerpCollateral,
  PerpPosition,
  PerpStats,
  Position,
  Rules,
  Settings,
  Ticker,
  Trade,
)
from tribulnation.sdk.market.types.candles import candle_windows
from typed_aster.schemas import BatchError
from .base import ExchangeMixin
from ..core import Scope

from tribulnation.sdk.market import PerpExchange as SDKExchange
from typed_aster.futures.trade.schemas import FuturesOrder


def order_state(row: FuturesOrder) -> OrderState:
  """Preserve native order quantities and reject incomplete order responses."""
  if 'price' not in row or 'origQty' not in row or 'executedQty' not in row:
    raise NotImplementedError('Order response lacks SDK quantities or price')
  sign = 1 if row['side'] == 'BUY' else -1
  return OrderState(
    id=str(row['orderId']),
    price=row['price'],
    qty=sign * row['origQty'],
    filled_qty=sign * row['executedQty'],
    active=row['status'] in ('NEW', 'PARTIALLY_FILLED'),
    details=row,
  )


class ErrorBody(TypedDict):
  """The documented order-not-found envelope, excluding request credentials."""

  code: int
  msg: str


error_body = TypeAdapter(ErrorBody)


@dataclass(frozen=True, kw_only=True)
class PerpExchange(ExchangeMixin, SDKExchange):
  """The perp exchange; unsupported PoC mappings remain explicit failures."""

  @property
  def exchange_id(self) -> Scope:
    """Identify this exchange within Aster."""
    return 'perp'

  async def market(self, market_id: str, /):
    """Resolve an active native symbol into a market sharing this client."""
    from .market import PerpMarket

    if market_id not in await self.markets():
      raise ValueError(f'Unknown Aster perp market: {market_id}')
    return PerpMarket(exchange=self, symbol=market_id)

  async def markets(self) -> Sequence[str]:
    """List native active perp symbols on the selected network."""
    info = await self.call_aster(lambda: self.client.futures.market.exchange_info())
    return [
      r['symbol']
      for r in info['symbols']
      if r['status'] == 'TRADING' and r['contractType'] == 'PERPETUAL'
    ]

  async def depth(self, market_id: str, /, *, levels: int | None = None) -> Book:
    """Read native base-unit book quantities, then trim to the requested depth."""
    if levels is not None and (not 1 <= levels <= 1000):
      raise ValueError('levels must be between 1 and 1000')
    raw = await self.call_aster(
      lambda: self.client.futures.market.depth(market_id, limit=1000)
    )
    book = Book(
      bids=[Book.Entry(*r) for r in raw['bids']],
      asks=[Book.Entry(*r) for r in raw['asks']],
    )
    return book if levels is None else book.limit(levels)

  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, Ticker]:
    """Join native rolling volume and best-book fields by symbol."""
    if markets is not None and (not markets):
      return {}
    stats = await self.call_aster(lambda: self.client.futures.market.ticker_24hr())
    quotes = await self.call_aster(lambda: self.client.futures.market.book_ticker())
    stats = stats if isinstance(stats, list) else [stats]
    quotes = quotes if isinstance(quotes, list) else [quotes]
    books = {r['symbol']: r for r in quotes}
    symbols = (
      await self.call_aster(lambda: self.client.futures.market.exchange_info())
    )['symbols']
    wanted = {
      r['symbol']
      for r in symbols
      if r['status'] == 'TRADING' and r['contractType'] == 'PERPETUAL'
    }
    if markets is not None:
      wanted.intersection_update(markets)
    result: dict[str, Ticker] = {}
    for row in stats:
      if row['symbol'] not in wanted:
        continue
      quote = books.get(row['symbol'])
      result[row['symbol']] = Ticker(
        last=row['lastPrice'],
        base_volume_24h=row['volume'],
        quote_volume_24h=row['quoteVolume'],
        bid=quote['bidPrice'] if quote else None,
        ask=quote['askPrice'] if quote else None,
        bid_qty=quote['bidQty'] if quote else None,
        ask_qty=quote['askQty'] if quote else None,
      )
    return result

  async def rules(self, market_id: str, /, *, refetch: bool = False) -> Rules:
    """Map explicit futures filters; leave the public fee schedule unknown."""
    row = next(
      (
        r
        for r in (
          await self.call_aster(lambda: self.client.futures.market.exchange_info())
        )['symbols']
        if r['symbol'] == market_id
      )
    )
    price = next((f for f in row['filters'] if f['filterType'] == 'PRICE_FILTER'))
    lot = next((f for f in row['filters'] if f['filterType'] == 'LOT_SIZE'))
    notional = next(
      (f for f in row['filters'] if f['filterType'] == 'MIN_NOTIONAL'), None
    )
    percent = next(
      (f for f in row['filters'] if f['filterType'] == 'PERCENT_PRICE'), None
    )
    return Rules(
      fee_asset=row['marginAsset'],
      tick_size=price['tickSize'],
      step_size=lot['stepSize'],
      fixed_min_qty=lot['minQty'] or None,
      max_qty=lot['maxQty'] or None,
      fixed_min_price=price['minPrice'] or None,
      fixed_max_price=price['maxPrice'] or None,
      min_value=notional['notional'] if notional else None,
      rel_min_price=percent['multiplierDown'] if percent else None,
      rel_max_price=percent['multiplierUp'] if percent else None,
      api=row['status'] == 'TRADING',
      fees=None,
      details=row,
    )

  async def fees(self, market_id: str, /, *, refetch: bool = False) -> Fees:
    """Read this account's native maker and taker commission rates."""
    row = await self.call_aster(
      lambda: self.client.futures.account.commission_rate(market_id)
    )
    return Fees.symmetric(
      maker=row['makerCommissionRate'], taker=row['takerCommissionRate']
    )

  @PaginatedResponse.lift
  async def candles(
    self, market_id: str, /, interval: CandleInterval, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Candle]]:
    """Read half-open trade-candle windows without filling empty intervals."""
    for lower, upper in candle_windows(start, end, interval, size=500):
      rows = await self.call_aster(
        lambda: self.client.futures.market.klines(
          market_id,
          interval=interval,
          start_time=lower,
          end_time=upper - timedelta(milliseconds=1),
          limit=500,
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

  async def query_order(self, market_id: str, /, id: str) -> OrderState | None:
    """Return None only for the venue's documented nonexistent-order code."""
    try:
      row = await self.call_aster(
        lambda: self.client.futures.trade.order(
          {'symbol': market_id, 'orderId': int(id)}
        )
      )
    except BadRequest as exc:
      if len(exc.args) > 1 and error_body.validate_python(exc.args[1])['code'] == -2013:
        return None
      raise
    return order_state(row)

  async def open_orders(self, market_id: str, /) -> Sequence[OrderState]:
    """Map the account's validated open orders on this symbol."""
    return [
      order_state(r)
      for r in await self.call_aster(
        lambda: self.client.futures.trade.open_orders(market_id)
      )
    ]

  @overload
  def trades_history(
    self, market_id: None, /, start: datetime, end: datetime
  ) -> PaginatedResponse[ExchangeTrade]: ...

  @overload
  def trades_history(
    self, market_id: str, /, start: datetime, end: datetime
  ) -> PaginatedResponse[Trade]: ...

  @PaginatedResponse.lift
  async def trades_history(
    self, market_id: str | None, /, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Trade]]:
    """Wait for the typed paginator to stop combining mutually exclusive filters."""
    if market_id is None:
      raise NotImplementedError('Aster exchange-wide trade history is not qualified')
    raise NotImplementedError(
      'UserTrades.user_trades_paged combines exclusive time and ID filters; see typed-client-issues.md'
    )
    yield []

  async def position(self, market_id: str, /) -> Position:
    """Use the venue's signed one-way position amount, including native zero."""
    rows = await self.call_aster(lambda: self.client.futures.position.risk(market_id))
    if len(rows) != 1 or rows[0]['positionSide'] != 'BOTH':
      raise NotImplementedError('Only one-way positions are qualified by this PoC')
    return Position(size=rows[0]['positionAmt'])

  async def available_notional(self, market_id: str, /) -> Decimal:
    """No account-side buy/sell capacity figure; remaining_openable_notional_value is a symbol-wide cap."""
    raise NotImplementedError(
      'No account-side buy/sell capacity figure; remaining_openable_notional_value is a symbol-wide cap'
    )

  async def place_order(
    self, market_id: str, /, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Map signed base quantity and native MARKET, GTC and GTX order types."""
    if settings:
      raise NotImplementedError('Aster-specific settings are not declared in the SDK')
    qty = Decimal(str(order['qty']))
    if not qty.is_finite() or not qty:
      raise ValueError('Order quantity must be finite and nonzero')
    if order['type'] == 'MARKET':
      row = await self.call_aster(
        lambda: self.client.futures.trade.place_order(
          {
            'symbol': market_id,
            'side': 'BUY' if qty > 0 else 'SELL',
            'type': 'MARKET',
            'quantity': abs(qty),
            'newOrderRespType': 'RESULT',
          }
        )
      )
    else:
      price = Decimal(str(order['price']))
      if not price.is_finite() or price <= 0:
        raise ValueError('Limit price must be finite and positive')
      row = await self.call_aster(
        lambda: self.client.futures.trade.place_order(
          {
            'symbol': market_id,
            'side': 'BUY' if qty > 0 else 'SELL',
            'type': 'LIMIT',
            'quantity': abs(qty),
            'price': price,
            'timeInForce': 'GTX' if order['type'] == 'POST_ONLY' else 'GTC',
            'newOrderRespType': 'RESULT',
          }
        )
      )
    return OrderResponse(id=str(row['orderId']), details=row)

  async def cancel_order(
    self, market_id: str, /, id: str, *, settings: Settings = {}
  ) -> Any:
    """Cancel one native order and return the venue acknowledgement."""
    if settings:
      raise NotImplementedError('Aster-specific settings are not declared in the SDK')
    return await self.call_aster(
      lambda: self.client.futures.trade.cancel_order(
        {'symbol': market_id, 'orderId': int(id)}
      )
    )

  async def cancel_orders(
    self, market_id: str, /, ids: Sequence[str], *, settings: Settings = {}
  ) -> Any:
    """Chunk at the native ten-order limit, preserving every per-order result."""
    if settings:
      raise NotImplementedError('Aster-specific settings are not declared in the SDK')
    results: list[FuturesOrder | BatchError] = []
    for offset in range(0, len(ids), 10):
      results.extend(
        await self.call_aster(
          lambda: self.client.futures.trade.cancel_batch_orders(
            {
              'symbol': market_id,
              'orderIdList': [int(id) for id in ids[offset : offset + 10]],
            }
          )
        )
      )
    return results

  async def cancel_open_orders(
    self, market_id: str, /, *, settings: Settings = {}
  ) -> Any:
    """Cancel all orders for the selected native symbol."""
    if settings:
      raise NotImplementedError('Aster-specific settings are not declared in the SDK')
    return await self.call_aster(
      lambda: self.client.futures.trade.cancel_all_open_orders(market_id)
    )

  async def index(self, market_id: str, /, *, settings: Settings = {}) -> Decimal:
    """Read the venue's index price directly from premiumIndex."""
    row = await self.call_aster(
      lambda: self.client.futures.market.premium_index(market_id)
    )
    if isinstance(row, list):
      row = next((r for r in row if r['symbol'] == market_id))
    return row['indexPrice']

  async def next_funding(self, market_id: str, /) -> NextFunding:
    """Read the native funding quote, settlement time and per-symbol interval."""
    row = await self.call_aster(
      lambda: self.client.futures.market.premium_index(market_id)
    )
    if isinstance(row, list):
      row = next((r for r in row if r['symbol'] == market_id))
    config = next(
      (
        r
        for r in await self.call_aster(
          lambda: self.client.futures.market.funding_info(market_id)
        )
        if r['symbol'] == market_id
      )
    )
    return NextFunding(
      rate=row['lastFundingRate'],
      time=row['nextFundingTime'],
      interval=timedelta(hours=config['fundingIntervalHours']),
    )

  async def perp_stats(
    self, markets: Collection[str] | None = None, *, settings: Settings = {}
  ) -> Mapping[str, PerpStats]:
    """Wait for the client to validate the complete native funding configuration."""
    raise NotImplementedError(
      'FundingInfo configuration fields are null on some testnet response rows'
    )

  @PaginatedResponse.lift
  async def funding_rates(
    self, market_id: str, /, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Sequence[FundingRate]]:
    """Page actual funding settlements without calculating a substitute rate."""
    async for page in self.client.futures.market.funding_rate_paged(
      market_id, start_time=start, end_time=end, limit=1000
    ).via(self.call_aster):
      yield [FundingRate(rate=r['fundingRate'], time=r['fundingTime']) for r in page]

  @overload
  def funding_payments(
    self, market_id: None, /, start: datetime, end: datetime
  ) -> PaginatedResponse[ExchangeFundingPayment]: ...

  @overload
  def funding_payments(
    self, market_id: str, /, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]: ...

  @PaginatedResponse.lift
  async def funding_payments(
    self, market_id: str | None, /, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[FundingPayment]]:
    """Funding payments have only been exercised with an empty response."""
    if market_id is None:
      raise NotImplementedError(
        'Aster exchange-wide funding payments are not qualified'
      )
    raise NotImplementedError(
      'Aster funding payments await a verified nonzero testnet sample'
    )
    yield []

  async def perp_position(self, market_id: str, /) -> PerpPosition:
    """Read the native signed amount and entry price for one-way positions."""
    rows = await self.call_aster(lambda: self.client.futures.position.risk(market_id))
    if len(rows) != 1 or rows[0]['positionSide'] != 'BOTH':
      raise NotImplementedError('Only one-way positions are qualified by this PoC')
    return PerpPosition(size=rows[0]['positionAmt'], entry_price=rows[0]['entryPrice'])

  async def collateral(self, market_id: str | None = None, /) -> Collateral:
    """Read native USDT equity and available margin for the shared cross bucket."""
    if market_id is not None:
      positions = await self.call_aster(
        lambda: self.client.futures.position.risk(market_id)
      )
      if not positions or any((row['marginType'] != 'cross' for row in positions)):
        raise NotImplementedError(
          'The API does not expose isolated available collateral'
        )
    row = await self.call_aster(
      lambda: self.client.futures.account.info_with_join_margin()
    )
    return Collateral(
      equity=row['totalMarginBalance'], free_collateral=row['availableBalance']
    )

  async def perp_collateral(self, market_id: str | None = None, /) -> PerpCollateral:
    """The API publishes configured leverage, not the SDK aggregate notional/equity leverage figure."""
    raise NotImplementedError(
      'The API publishes configured leverage, not the SDK aggregate notional/equity leverage figure'
    )
