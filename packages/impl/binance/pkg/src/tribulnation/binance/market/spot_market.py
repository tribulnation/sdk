"""Binance spot market."""

from typing_extensions import (
  AsyncContextManager,
  AsyncIterable,
  AsyncIterator,
  Literal,
  Sequence,
)
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from tribulnation.sdk.core import OverflowPolicy, PaginatedResponse
from tribulnation.sdk.market import (
  Market,
  Book,
  Candle,
  CandleInterval,
  Collateral,
  Order,
  OrderResponse,
  OrderState,
  Position,
  Rules,
  Settings,
  Trade,
)

from typed_binance.spot.streams.partial_depth import PartialDepthEvent
from typed_binance.spot.ws.user_data.events import UserDataPush

from tribulnation.binance.util import windows

from .impl import SharedMixin, wrap_exceptions, not_implemented

TRADES_WINDOW = timedelta(hours=24)
"""`myTrades` refuses a window wider than 24h."""

CANDLES_PAGE = 1000
"""Rows per `klines` page; Binance's documented maximum."""

CANDLE_INTERVALS = frozenset[CandleInterval]({'1m', '5m', '15m', '1h', '4h', '1d'})
"""Every contract interval is a Binance `klines` interval under the same name."""


def stream_levels(levels: int | None) -> Literal[5, 10, 20]:
  """Round `levels` up to the smallest depth the WS stream actually serves."""
  if levels is None or levels > 10:
    return 20
  if levels > 5:
    return 10
  return 5


async def drop_none(stream: AsyncIterable[Trade | None]) -> AsyncIterator[Trade]:
  """Keep only the pushes that parsed into a trade."""
  async for trade in stream:
    if trade is not None:
      yield trade


@asynccontextmanager
async def trades_only(
  manager: AsyncContextManager[AsyncIterable[Trade | None]],
) -> AsyncIterator[AsyncIterable[Trade]]:
  """Narrow a user-data subscription down to its trade pushes."""
  async with manager as stream:
    yield drop_none(stream)


@dataclass(frozen=True, kw_only=True)
class SpotMarket(SharedMixin, Market):
  """A Binance spot market."""

  CANDLE_INTERVALS = CANDLE_INTERVALS

  symbol: str

  @property
  def venue_id(self) -> str:
    return 'binance'

  @property
  def exchange_id(self) -> str:
    return 'spot'

  @property
  def market_id(self) -> str:
    return self.symbol

  @wrap_exceptions
  async def depth(self, *, levels: int | None = None) -> Book:
    raw = await self.client.spot.http.market.order_book(
      symbol=self.symbol, limit=levels
    )
    return Book(
      bids=[Book.Entry(price, qty) for price, qty in raw['bids']],
      asks=[Book.Entry(price, qty) for price, qty in raw['asks']],
    )

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """Subscribe to the order book over Binance's public partial-depth WS stream.

    `queue_size`/`overflow` are accepted for interface compatibility and ignored: each
    call opens its own independent subscription rather than fanning out a shared one.
    """

    def to_book(event: PartialDepthEvent) -> Book:
      return Book(
        bids=[Book.Entry(price, qty) for price, qty in event['bids']],
        asks=[Book.Entry(price, qty) for price, qty in event['asks']],
      )

    return self.client.spot.streams.partial_depth(
      self.symbol.lower(), levels=stream_levels(levels)
    ).map(to_book)

  @wrap_exceptions
  async def rules(self, *, refetch: bool = False) -> Rules:
    symbols = await self.shared.load_spot_symbols(refetch=refetch)
    sym = symbols[self.symbol]
    filters = sym['filters']
    price_filter = next((f for f in filters if f['filterType'] == 'PRICE_FILTER'), None)
    lot_size = next((f for f in filters if f['filterType'] == 'LOT_SIZE'), None)
    notional = next(
      (f for f in filters if f['filterType'] == 'NOTIONAL'), None
    ) or next((f for f in filters if f['filterType'] == 'MIN_NOTIONAL'), None)
    account = await self.client.spot.http.account.info()
    commission = account['commissionRates']
    return Rules(
      base=sym['baseAsset'],
      quote=sym['quoteAsset'],
      fee_asset=sym['quoteAsset'],
      tick_size=price_filter['tickSize'] if price_filter else Decimal(0),
      step_size=lot_size['stepSize'] if lot_size else Decimal(0),
      fixed_min_qty=lot_size['minQty'] if lot_size else None,
      min_value=notional['minNotional'] if notional else None,
      max_qty=lot_size['maxQty'] if lot_size else None,
      maker_fee=commission['maker'],
      taker_fee=commission['taker'],
      api=sym['isSpotTradingAllowed'],
      details=sym,
    )

  def candles(
    self,
    interval: CandleInterval,
    start: datetime | None = None,
    end: datetime | None = None,
  ) -> PaginatedResponse[Candle]:
    """Fetch historical trade candles, one page per `klines` request.

    Binance walks forwards and bounds both ends on open time inclusively, which is
    the contract's own shape, so the client's paged walk is yielded as it comes. An
    open `start` is answered from the venue's earliest kline.
    """
    self.check_interval(interval)
    return PaginatedResponse(self.walk_candles(interval, start, end))

  async def walk_candles(
    self, interval: CandleInterval, start: datetime | None, end: datetime | None
  ) -> AsyncIterator[Sequence[Candle]]:
    """The pages behind `candles`."""
    paging = self.client.spot.http.market.klines_paged(
      symbol=self.symbol,
      interval=interval,
      start_time=start,
      end_time=end,
      limit=CANDLES_PAGE,
    ).via(self.call_binance)
    async for rows in paging:
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
      ]

  @wrap_exceptions
  async def open_orders(self) -> Sequence[OrderState]:
    raw = await self.client.spot.http.account.open_orders(symbol=self.symbol)
    out: list[OrderState] = []
    for o in raw:
      # `account.open_orders` still declares its decimal strings as bare `str`, unlike
      # the fill and balance endpoints, so these three stay wrapped.
      orig_qty = Decimal(o['origQty'])
      executed_qty = Decimal(o['executedQty'])
      sign = 1 if o['side'] == 'BUY' else -1
      out.append(
        OrderState(
          id=str(o['orderId']),
          price=Decimal(o['price']),
          qty=sign * orig_qty,
          filled_qty=sign * executed_qty,
          active=o['status'] in ('NEW', 'PARTIALLY_FILLED'),
          details=o,
        )
      )
    return out

  @PaginatedResponse.lift
  async def trades_history(self, start: datetime, end: datetime):
    """Fetch trades history, one page per 24h window (`myTrades`' own limit)."""
    for window_start, window_end in windows(start, end, TRADES_WINDOW):
      raw = await self.call_binance(
        lambda: self.client.spot.http.account.my_trades(
          symbol=self.symbol,
          start_time=window_start,
          end_time=window_end,
          limit=1000,
        )
      )
      if raw:
        yield [
          Trade(
            id=str(t['id']),
            price=t['price'],
            qty=t['qty'] if t['isBuyer'] else -t['qty'],
            time=t['time'],
            maker=t['isMaker'],
            fee=Trade.Fee(amount=t['commission'], asset=t['commissionAsset']),
            details=t,
          )
          for t in raw
        ]

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """Subscribe to your real-time trades.

    Spot has no listenKey market-stream for user data (unlike futures); this upgrades
    the WS API connection itself with a signed `userDataStream.subscribe`.
    `queue_size`/`overflow` are accepted for interface compatibility and ignored: each
    call opens its own independent subscription rather than fanning out a shared one.
    """

    def parse(push: UserDataPush) -> Trade | None:
      event = push['event']
      if event['e'] != 'executionReport' or event['x'] != 'TRADE':
        return None
      if event['s'] != self.symbol:
        return None
      qty = event['l']
      fee_asset = event['N']
      return Trade(
        id=str(event['t']),
        price=event['L'],
        qty=qty if event['S'] == 'BUY' else -qty,
        time=event['T'],
        maker=event['m'],
        # `N` is null when no commission was charged -- the only nullable half of the pair.
        fee=Trade.Fee(amount=event['n'], asset=fee_asset)
        if fee_asset is not None
        else None,
        details=event,
      )

    return trades_only(self.client.spot.ws.user_data.events().map(parse))

  @wrap_exceptions
  async def position(self) -> Position:
    symbols = await self.shared.load_spot_symbols()
    base = symbols[self.symbol]['baseAsset']
    account = await self.client.spot.http.account.info()
    balance = next((b for b in account['balances'] if b['asset'] == base), None)
    size = (balance['free'] + balance['locked']) if balance else Decimal(0)
    return Position(size=size)

  @wrap_exceptions
  async def collateral(self) -> Collateral:
    symbols = await self.shared.load_spot_symbols()
    quote = symbols[self.symbol]['quoteAsset']
    account = await self.client.spot.http.account.info()
    balance = next((b for b in account['balances'] if b['asset'] == quote), None)
    free = balance['free'] if balance else Decimal(0)
    locked = balance['locked'] if balance else Decimal(0)
    return Collateral(equity=free + locked, free_collateral=free)

  @wrap_exceptions
  async def available_notional(self) -> Decimal:
    collateral = await self.collateral()
    return collateral.free_collateral

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    raise not_implemented('place_order', self.id)

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> object:
    raise not_implemented('cancel_order', self.id)
