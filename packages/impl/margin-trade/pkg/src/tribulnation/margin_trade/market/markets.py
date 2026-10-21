"""Spot and perpetual Market objects over margin.trade coin names."""

from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import secrets
from typing_extensions import (
  Any,
  AsyncContextManager,
  AsyncIterable,
  ClassVar,
  Literal,
  Sequence,
)
from typed_margin_trade.exchange.cancel import CancelSpec
from typed_margin_trade.info.candle_snapshot import CandleRange
from typed_margin_trade.schemas import OrderSpec, PerpUniverseItem
from tribulnation.sdk.core import (
  ApiError,
  OrderRejected,
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
from ..core import (
  FUNDING_INTERVAL,
  PERP_FEE_ASSET,
  PERP_PRICE_DECIMALS,
  SPOT_ASSET_OFFSET,
  SPOT_PRICE_DECIMALS,
  Pair,
  Public,
  order_state,
  parse_book,
  parse_trade,
  round_price,
  tick_size,
)
from .collateral import cross_collateral

CANDLE_WIDTHS: dict[CandleInterval, timedelta] = {
  '1m': timedelta(minutes=1),
  '5m': timedelta(minutes=5),
  '15m': timedelta(minutes=15),
  '1h': timedelta(hours=1),
  '4h': timedelta(hours=4),
  '1d': timedelta(days=1),
}
TIME_IN_FORCE: dict[str, Literal['Gtc', 'Alo', 'Ioc']] = {
  'LIMIT': 'Gtc',
  'POST_ONLY': 'Alo',
  'MARKET': 'Ioc',
}
"""`MARKET` is an IOC limit at the SDK's protection price: the venue has no market order
type, and refuses an IOC priced too far through the book with `slippage exceeded`."""


def next_settlement(now: datetime) -> datetime:
  """The next hourly funding settlement after `now`."""
  return now.replace(minute=0, second=0, microsecond=0) + FUNDING_INTERVAL


@dataclass(frozen=True, kw_only=True)
class NativeMarket(Public, Market):
  """What spot pairs and perpetuals share: books, candles, orders and fills by coin."""

  CANDLE_INTERVALS: ClassVar[frozenset[CandleInterval]] = frozenset(CANDLE_WIDTHS)

  @property
  @abstractmethod
  def coin(self) -> str:
    """The venue's coin name: `BTC`, `PEARL/USDC`."""

  @property
  @abstractmethod
  def asset(self) -> int:
    """The asset index order actions address."""

  @property
  @abstractmethod
  def sz_decimals(self) -> int:
    """Size decimals of the market."""

  @property
  @abstractmethod
  def price_decimals(self) -> int:
    """Price decimals before the size decimals are taken off."""

  @property
  def market_id(self) -> str:
    """The coin name."""
    return self.coin

  async def depth(self, *, levels: int | None = None, settings: Settings = {}) -> Book:
    """The `l2Book` snapshot (up to 20 levels per side)."""
    raw = await self.shared.call(lambda: self.client.info.l2_book(self.coin))
    return parse_book(raw, levels)

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """Full `l2Book` snapshots from one shared subscription per coin."""
    return self.shared.stream(
      self.shared.books,
      self.coin,
      lambda: self.shared.connect_book(self.coin),
      select=lambda book: book.limit(levels) if levels else book,
      queue_size=queue_size,
      overflow=overflow,
    )

  async def fees(self, *, refetch: bool = False) -> Fees:
    """Not supported: `userFees` reports one account-wide rate, while fills are charged
    the market's own rate (see `rules().fees`)."""
    raise NotImplementedError(
      f'margin.trade publishes no per-account rate per market [{self.id}]'
    )

  def candles(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> PaginatedResponse[Candle]:
    """Trade candles opening in `[start, end)`."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(self.candle_pages(interval, start, end))

  async def candle_pages(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Candle]]:
    """Walk forward from `start`, past the last opening time each response reaches."""
    cursor = start
    while cursor < end:
      req: CandleRange = {
        'coin': self.coin,
        'interval': interval,
        'startTime': cursor,
        'endTime': end - timedelta(milliseconds=1),
      }
      rows = await self.shared.call(lambda: self.client.info.candle_snapshot(req))
      if not rows:
        return
      page = [
        Candle(
          time=r['t'],
          open=r['o'],
          high=r['h'],
          low=r['l'],
          close=r['c'],
          volume=r['v'],
          trades=r['n'],
        )
        for r in rows
        if start <= r['t'] < end
      ]
      if page:
        yield page
      cursor = max(r['t'] for r in rows) + CANDLE_WIDTHS[interval]

  async def query_order(self, id: str) -> OrderState | None:
    """`orderStatus` by exchange order ID. It trails placement and cancellation by
    about a second: a just-placed order reads `None`, a just-cancelled one active."""
    found = await self.shared.call(
      lambda: self.client.info.order_status(user=self.shared.address, oid=int(id))
    )
    if 'order' in found and found['order']['order']['coin'] == self.coin:
      entry = found['order']
      return order_state(entry['order'], active=entry['status'] == 'open')

  async def open_orders(self) -> Sequence[OrderState]:
    """Resting orders from `frontendOpenOrders`, which reflects changes at once."""
    rows = await self.shared.call(
      lambda: self.client.info.frontend_open_orders(user=self.shared.address)
    )
    return [order_state(row, active=True) for row in rows if row['coin'] == self.coin]

  @PaginatedResponse.lift
  async def trades_history(
    self, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Trade]]:
    """This coin's fills within inclusive bounds, newest first (`userFillsByTime`)."""
    pages = self.client.info.user_fills_by_time_paged(
      self.shared.address, start_time=start, end_time=end
    )
    async for page in pages.via(self.shared.call):
      if rows := [parse_trade(f) for f in page if f['coin'] == self.coin]:
        yield rows

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """The account's fills on this coin, from one shared `userFills` subscription."""
    return self.shared.stream(
      self.shared.fills,
      self.coin,
      lambda: self.shared.connect_fills(self.coin),
      select=lambda trade: trade,
      queue_size=queue_size,
      overflow=overflow,
    )

  def random_client_order_id(self) -> str:
    """A `cloid`: `0x` and 128 random bits as 32 hex digits."""
    return f'0x{secrets.token_hex(16)}'

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """
    Place a LIMIT (`Gtc`), POST_ONLY (`Alo`) or MARKET (`Ioc` at `price`) order.

    The price is rounded to the venue's precision. `filled_qty` is reported for orders
    that fill on placement; a resting order reports none.

    Raises:
      OrderRejected: The order's own status is an error (nothing rests or filled).
    """
    qty = Decimal(order['qty'])
    spec: OrderSpec = {
      'a': self.asset,
      'b': qty > 0,
      'p': round_price(
        Decimal(order['price']), max_decimals=self.price_decimals - self.sz_decimals
      ),
      's': abs(qty),
      'r': False,
      't': {'limit': {'tif': TIME_IN_FORCE[order['type']]}},
    }
    if (cloid := order.get('client_order_id')) is not None:
      spec['c'] = cloid
    result = await self.shared.call(
      lambda: self.client.exchange.order([spec], grouping='na')
    )
    if not result['statuses']:
      raise ApiError('margin.trade answered no order status', result)
    status = result['statuses'][0]
    if 'error' in status:
      raise OrderRejected(status['error'], result)
    if 'resting' in status:
      return OrderResponse(id=str(status['resting']['oid']), details=status)
    filled = status['filled']
    return OrderResponse(
      id=str(filled['oid']), details=status, filled_qty=filled['totalSz']
    )

  async def cancel_orders(self, ids: Sequence[str], *, settings: Settings = {}) -> Any:
    """Cancel in one action; each order reports its own status."""
    if not ids:
      return []
    cancels: list[CancelSpec] = [{'a': self.asset, 'o': int(id)} for id in ids]
    result = await self.shared.call(lambda: self.client.exchange.cancel(cancels))
    return result['statuses']

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """Cancel one order.

    Raises:
      ApiError: The venue refused it (e.g. `order not found`).
    """
    statuses = await self.cancel_orders([id])
    if not statuses or statuses[0] != 'success':
      raise ApiError(f'margin.trade did not cancel order {id}', statuses)
    return statuses[0]

  async def cancel_open_orders(self, *, settings: Settings = {}) -> Any:
    """Cancel every resting order of this coin in one action."""
    return await self.cancel_orders([o.id for o in await self.open_orders()])


@dataclass(frozen=True, kw_only=True)
class SpotMarket(NativeMarket):
  """A spot pair, named `<base>/<quote>`."""

  meta: Pair

  @property
  def exchange_id(self) -> str:
    """The spot exchange ID."""
    return 'spot'

  @property
  def coin(self) -> str:
    """The pair name."""
    return self.meta.pair['name']

  @property
  def asset(self) -> int:
    """`10000 + pair index`."""
    return SPOT_ASSET_OFFSET + self.meta.pair['index']

  @property
  def sz_decimals(self) -> int:
    """The base token's size decimals."""
    return self.meta.base['szDecimals']

  @property
  def price_decimals(self) -> int:
    """Spot prices take up to `8 - szDecimals` decimals."""
    return SPOT_PRICE_DECIMALS

  async def rules(self, *, refetch: bool = False) -> Rules:
    """The pair's own fees and precision. Minimums are side-specific
    (`spotMinBuyQuoteAmount`, `spotMinSellBaseQuantity`) and stay in `details`; fills
    name their fee asset."""
    meta = (await self.shared.spot_pairs(refetch=refetch))[self.coin]
    pair = meta.pair
    return Rules(
      fee_asset=None,
      tick_size=tick_size(meta.base['szDecimals'], max_decimals=SPOT_PRICE_DECIMALS),
      step_size=Decimal(10) ** -meta.base['szDecimals'],
      fees=Fees(
        maker_buy=pair['makerFee'],
        maker_sell=pair['makerFee'],
        taker_buy=pair['takerFee'],
        taker_sell=pair['takerFee'],
      ),
      api=True,
      details=pair,
    )

  async def balance(self, token: int) -> tuple[Decimal, Decimal]:
    """`(total, hold)` of one spot token, zero when the account holds none."""
    state = await self.shared.call(
      lambda: self.client.info.spot_clearinghouse_state(self.shared.address)
    )
    for row in state['balances']:
      if row['token'] == token:
        return row['total'], row['hold']
    return Decimal(0), Decimal(0)

  async def position(self) -> Position:
    """The base token's spot total, resting sells included."""
    total, _ = await self.balance(self.meta.base['index'])
    return Position(size=total)

  async def collateral(self) -> Collateral:
    """The quote token's spot balance; free is what resting buys do not hold."""
    total, hold = await self.balance(self.meta.quote['index'])
    return Collateral(equity=total, free_collateral=total - hold)


@dataclass(frozen=True, kw_only=True)
class PerpMarket(NativeMarket, SDKPerpMarket):
  """A USDC-margined perpetual, named by its coin."""

  meta: PerpUniverseItem

  @property
  def exchange_id(self) -> str:
    """The perpetual exchange ID."""
    return 'perp'

  @property
  def coin(self) -> str:
    """The market name."""
    return self.meta['name']

  @property
  def asset(self) -> int:
    """The universe item's `index`, not its list position."""
    return self.meta['index']

  @property
  def sz_decimals(self) -> int:
    """The market's size decimals."""
    return self.meta['szDecimals']

  @property
  def price_decimals(self) -> int:
    """Perpetual prices take up to `6 - szDecimals` decimals."""
    return PERP_PRICE_DECIMALS

  async def rules(self, *, refetch: bool = False) -> Rules:
    """The market's own `takerFee`/`makerFee`, charged in USD, and its precision."""
    item = (await self.shared.perp_universe(refetch=refetch))[self.coin]
    return Rules(
      fee_asset=PERP_FEE_ASSET,
      tick_size=tick_size(item['szDecimals'], max_decimals=PERP_PRICE_DECIMALS),
      step_size=Decimal(10) ** -item['szDecimals'],
      fees=Fees(
        maker_buy=item['makerFee'],
        maker_sell=item['makerFee'],
        taker_buy=item['takerFee'],
        taker_sell=item['takerFee'],
      ),
      api=not item.get('isDelisted', False),
      details=item,
    )

  async def index(self, *, settings: Settings = {}) -> Decimal:
    """The oracle price."""
    _, ctx = (await self.shared.contexts())[self.coin]
    return ctx['oraclePx']

  async def next_funding(self) -> NextFunding:
    """The current funding rate and premium, settled at the next full hour."""
    _, ctx = (await self.shared.contexts())[self.coin]
    return NextFunding(
      rate=ctx['funding'],
      time=next_settlement(datetime.now(timezone.utc)),
      interval=FUNDING_INTERVAL,
      premium=ctx['premium'],
    )

  def funding_rates(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> PaginatedResponse[FundingRate]:
    """Not supported: `fundingHistory` serves placeholder data only."""
    raise NotImplementedError(
      f'margin.trade serves no funding-rate history [{self.id}]'
    )

  @PaginatedResponse.lift
  async def funding_payments(
    self, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[FundingPayment]]:
    """This coin's settlements within inclusive bounds, received-positive."""
    rows = await self.shared.call(
      lambda: self.client.info.user_funding(
        self.shared.address, start_time=start, end_time=end
      )
    )
    if page := [
      FundingPayment(amount=r['delta']['usdc'], time=r['time'])
      for r in rows
      if r['delta']['coin'] == self.coin
    ]:
      yield page

  async def perp_position(self) -> PerpPosition:
    """The one-way position, flat when absent."""
    state = await self.shared.call(
      lambda: self.client.info.clearinghouse_state(user=self.shared.address)
    )
    for entry in state['assetPositions']:
      if (pos := entry['position'])['coin'] == self.coin:
        return PerpPosition(size=pos['szi'], entry_price=pos['entryPx'])
    return PerpPosition(size=Decimal(0), entry_price=Decimal(0))

  async def leverage(self, *, refetch: bool = False) -> Decimal:
    """The account's `activeAssetData` leverage on this market, cached per coin."""
    if refetch or self.coin not in self.shared.leverages:
      data = await self.shared.call(
        lambda: self.client.info.active_asset_data(
          user=self.shared.address, coin=self.coin
        )
      )
      self.shared.leverages[self.coin] = Decimal(data['leverage']['value'])
    return self.shared.leverages[self.coin]

  async def perp_collateral(self) -> PerpCollateral:
    """The cross bucket; an isolated position's own bucket is not supported."""
    state = await self.shared.call(
      lambda: self.client.info.clearinghouse_state(user=self.shared.address)
    )
    for entry in state['assetPositions']:
      pos = entry['position']
      if pos['coin'] == self.coin and pos['leverage']['type'] == 'isolated':
        raise NotImplementedError(
          f'margin.trade isolated collateral is not supported [{self.id}]'
        )
    return cross_collateral(state)
