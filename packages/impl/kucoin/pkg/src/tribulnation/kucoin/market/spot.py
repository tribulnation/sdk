"""Classic spot pairs, traded through KuCoin's high-frequency (HF) order API."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing_extensions import Any, AsyncIterator, Sequence, cast

from typed_kucoin.spot.orders_hf.batch_add_sync import HfBatchAddOrderSyncResult
from typed_kucoin.streams.spot_margin_private.order_v2 import OrderChangeEvent
from tribulnation.sdk.core import Error, MissingData, OrderRejected, PaginatedResponse
from tribulnation.sdk.market import (
  Candle,
  CandleInterval,
  Fees,
  Order,
  OrderResponse,
  OrderState,
  Settings,
  SpotBalances,
  SpotMarket as SDKSpotMarket,
  SpotRules,
  Trade,
)
from ..errors import refused
from .account import spot_balance, spot_fees
from .candles import spot_candles
from .common import OrderEvent, Scope
from .native import NativeMarket, refusal, windows
from .orders import (
  NativeOrder,
  native_order,
  spot_event_trade,
  spot_order_state,
  spot_request,
  spot_trade,
)

TRADES_PAGE = 100
"""Fills per page of the HF fills endpoint."""


def dead(status: str | None, filled: Decimal | None) -> bool:
  """Whether a synchronous placement ended with nothing filled (a crossing post-only,
  an unmatched IOC), so nothing rests and nothing traded."""
  return status == 'done' and filled == 0


def batch_result(row: HfBatchAddOrderSyncResult) -> OrderResponse | Exception:
  """One synchronous batch item: its response, or the refusal KuCoin reported for it."""
  if not row['success']:
    return OrderRejected(row.get('failMsg', 'KuCoin refused the order'), row)
  elif dead(row.get('status'), row.get('dealSize')):
    return OrderRejected(f'Order {row["orderId"]} ended with nothing filled', row)
  else:
    return OrderResponse(id=row['orderId'], details=row, filled_qty=row.get('dealSize'))


@dataclass(frozen=True, kw_only=True)
class SpotMarket(NativeMarket, SDKSpotMarket):
  """A Classic spot pair, trading from the spot `trade` account."""

  @property
  def scope(self) -> Scope:
    """The spot product line."""
    return 'spot'

  @property
  def multiplier(self) -> Decimal:
    """Spot quantities already use base units."""
    return Decimal(1)

  async def rules(self, *, refetch: bool = False) -> SpotRules:
    """Return the pair's constraints and assets without fetching account fees."""
    row = (await self.shared.spot_symbols(refetch=refetch))[self.symbol]
    return SpotRules(
      base=row['baseCurrency'],
      quote=row['quoteCurrency'],
      fee_asset=row['feeCurrency'],
      tick_size=row['priceIncrement'],
      step_size=row['baseIncrement'],
      fixed_min_qty=row['baseMinSize'],
      max_qty=row['baseMaxSize'],
      min_value=row['minFunds'],
      api=row['enableTrading'],
      details=row,
    )

  async def fees(self, *, refetch: bool = False) -> Fees:
    """The account's actual rates on this pair (VIP tier and market-maker program
    included; a maker rebate is a negative rate), plus any tax rate KuCoin reports."""
    rows = await self.shared.call(
      lambda: self.client.account.trade_fee.actual_fee(self.symbol)
    )
    for row in rows:
      if row['symbol'] == self.symbol:
        return spot_fees(row)
    raise MissingData(
      'KuCoin fee rates omit the pair', market_id=self.symbol, field='symbol'
    )

  def candles(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> PaginatedResponse[Candle]:
    """Read native spot candles in required aware, half-open bounds."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(
      spot_candles(self.shared, self.symbol, interval, start, end)
    )

  async def balances(self, *, ttl: timedelta | None = None) -> SpotBalances:
    """The base and quote balances of the spot `trade` account.

    `total` is the account balance, `free` what is available (not held by orders).
    Funds in the `main` (funding) account are not tradable and not counted.
    """
    rules = await self.rules()
    rows = await self.shared.spot_accounts(ttl=ttl)
    return SpotBalances(
      base=spot_balance(rows, rules.base), quote=spot_balance(rows, rules.quote)
    )

  async def submit(self, order: NativeOrder) -> OrderResponse:
    """Place synchronously (`/hf/orders/sync`), so the answer carries the fill state."""
    row = await self.shared.call(
      lambda: self.client.spot.orders_hf.add_sync(spot_request(self.symbol, order))
    )
    if dead(row['status'], row['dealSize']):
      raise OrderRejected(f'Order {row["orderId"]} ended with nothing filled', row)
    return OrderResponse(id=row['orderId'], details=row, filled_qty=row['dealSize'])

  async def place_batch(
    self, orders: Sequence[Order]
  ) -> Sequence[OrderResponse | Exception]:
    """Place up to 20 orders in one synchronous batch; invalid ones are never sent.

    An order failing validation is answered with its `ValueError`, one KuCoin refused
    with `OrderRejected`; an error of the whole request answers every sent order.
    """
    rules = await self.rules()
    checked: list[NativeOrder | ValueError] = []
    for order in orders:
      try:
        checked.append(native_order(order, rules))
      except ValueError as exc:
        checked.append(exc)
    natives = [n for n in checked if isinstance(n, NativeOrder)]
    replies = iter(await self.send_batch(natives) if natives else [])
    return [next(replies) if isinstance(n, NativeOrder) else n for n in checked]

  async def send_batch(
    self, orders: Sequence[NativeOrder]
  ) -> Sequence[OrderResponse | Exception]:
    """Send validated orders in one `/hf/orders/multi/sync` request."""
    try:
      rows = await self.shared.call(
        lambda: self.client.spot.orders_hf.batch_add_sync(
          [spot_request(self.symbol, n) for n in orders]
        )
      )
    except Error as exc:
      return [refusal(exc) if refused(exc) else exc] * len(orders)
    return [batch_result(r) for r in rows]

  def cancel(self, id: str):
    """Cancel synchronously, so the answer is final."""
    return self.client.spot.orders_hf.cancel_by_order_id_sync(
      order_id=id, symbol=self.symbol
    )

  async def cancel_open_orders(self, *, settings: Settings = {}) -> Any:
    """Cancel every open HF order on this pair in one request."""
    return await self.shared.call(
      lambda: self.client.spot.orders_hf.cancel_all_by_symbol(self.symbol)
    )

  async def fetch_order(self, id: str) -> OrderState | None:
    """Read one HF order of this pair."""
    row = await self.shared.call(
      lambda: self.client.spot.orders_hf.get_by_order_id(
        order_id=id, symbol=self.symbol
      )
    )
    return spot_order_state(row) if row['symbol'] == self.symbol else None

  async def open_orders(self) -> Sequence[OrderState]:
    """Read this pair's open HF orders."""
    rows = await self.shared.call(
      lambda: self.client.spot.orders_hf.get_open_orders(self.symbol)
    )
    return [spot_order_state(r) for r in rows or []]

  def event_trade(self, event: OrderEvent) -> Trade | None:
    """A fill of this pair from the spot order channel."""
    row = cast(OrderChangeEvent, event)
    if row['symbol'] == self.symbol:
      return spot_event_trade(row)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Read this pair's HF fills within inclusive `[start, end]`, up to now.

    Walks seven-day windows. KuCoin answers a window beyond its retention with recent
    fills instead, so each window keeps only its own rows and each fill appears once.
    """
    if start.utcoffset() is None or end.utcoffset() is None:
      raise ValueError('Trade history bounds must be timezone-aware')
    return PaginatedResponse(self.trade_pages(start, end))

  async def trade_pages(
    self, start: datetime, end: datetime
  ) -> AsyncIterator[Sequence[Trade]]:
    """Page each window with the typed `lastId` pager, retrying each page."""
    seen: set[int] = set()
    for lower, upper in windows(start, end, datetime.now(timezone.utc)):
      pages = self.client.spot.orders_hf.get_trade_history_paged(
        symbol=self.symbol, start_at=lower, end_at=upper, limit=TRADES_PAGE
      )
      async for rows in pages.via(self.shared.call):
        fresh = [
          r for r in rows if lower <= r['createdAt'] <= upper and r['id'] not in seen
        ]
        seen.update(r['id'] for r in fresh)
        if fresh:
          yield [spot_trade(r) for r in fresh]
