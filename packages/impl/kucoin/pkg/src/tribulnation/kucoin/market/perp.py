"""Linear perpetuals on KuCoin Classic Futures: one-way positions on cross margin, in lots."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing_extensions import Any, AsyncIterator, Sequence, cast

from typed_kucoin.schemas import (
  FuturesAddOrderLimit,
  FuturesAddOrderMarket,
  FuturesBatchCancelResult,
  FuturesOrderEvent,
)
from tribulnation.sdk.core import (
  ApiError,
  Error,
  OrderRejected,
  PaginatedResponse,
)
from tribulnation.sdk.market import (
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
from tribulnation.sdk.util import whole_leverage
from ..errors import refused
from .account import (
  cross_collateral,
  isolated_collateral,
  perp_fees,
  perp_position,
  position_row,
)
from . import funding
from .candles import perp_candles
from .common import OrderEvent, Scope
from .native import NativeMarket, refusal, windows
from .orders import (
  batch_cancelled,
  batch_placed,
  order_leverage,
  NativeOrder,
  native_order,
  perp_event_trade,
  perp_order_state,
  perp_request,
  perp_trade,
)

POOL_CURRENCY = 'USDT'
"""The settlement currency of the `<account>:perp` pool."""
TRADES_PAGE = 100
"""Fills per page of the futures fills endpoint."""
FILL_TYPES = frozenset({'trade', 'liquid', 'adl'})
"""Fill classifications that change the position; `settlement` and `cancel` rows do not."""
BATCH_CANCEL = 10
"""Most orders one batch cancel takes."""


@dataclass(frozen=True, kw_only=True)
class LinearPerpMarket(NativeMarket, PerpMarket):
  """A linear perpetual: base-unit quantities on the SDK side, whole lots on the wire."""

  contract_multiplier: Decimal

  @property
  def scope(self) -> Scope:
    """The perpetual product line."""
    return 'perp'

  @property
  def multiplier(self) -> Decimal:
    """Base units per contract from the native contract definition."""
    return self.contract_multiplier

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Normalize native lot constraints, leaving unqualified fee schedules unknown."""
    row = (await self.shared.perp_symbols(refetch=refetch))[self.symbol]
    multiplier = Decimal(str(row['multiplier']))
    return Rules(
      fee_asset=row['settleCurrency'],
      tick_size=Decimal(str(row['tickSize'])),
      step_size=Decimal(row['lotSize']) * multiplier,
      fixed_min_qty=Decimal(row['lotSize']) * multiplier,
      max_qty=Decimal(row['maxOrderQty']) * multiplier,
      api=row['status'] == 'Open',
      details=row,
    )

  async def settle_currency(self) -> str:
    """The contract's settlement (margin) currency."""
    return (await self.shared.perp_symbols())[self.symbol]['settleCurrency']

  async def fees(self, *, refetch: bool = False) -> Fees:
    """The account's actual rates on this contract (VIP tier and market-maker program
    included; a maker rebate is a negative rate), plus any tax rate KuCoin reports."""
    row = await self.shared.call(
      lambda: self.shared.futures_api.trade_fee.actual_fee_futures(self.symbol)
    )
    return perp_fees(row)

  def candles(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> PaginatedResponse[Candle]:
    """Read trade candles, converting contract volume into base volume."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(
      perp_candles(self.shared, self.symbol, self.multiplier, interval, start, end)
    )

  async def index(self, *, settings: Settings = {}) -> Decimal:
    """Read the venue's published index price without a midpoint fallback."""
    row = await self.shared.call(lambda: self.client.futures.symbol(self.symbol))
    return Decimal(str(row['indexPrice']))

  async def next_funding(self, *, ttl: timedelta | None = None) -> NextFunding:
    """Use the dedicated funding endpoint's rate, settlement time and interval."""
    row = await self.shared.call(
      lambda: self.client.futures.funding_fees.current_funding_rate(self.symbol)
    )
    return NextFunding(
      rate=Decimal(str(row['value'])),
      time=row['fundingTime'],
      interval=timedelta(milliseconds=row['granularity']),
    )

  def funding_rates(
    self,
    start: datetime | None = None,
    end: datetime | None = None,
  ) -> PaginatedResponse[FundingRate]:
    """Page settled funding with inclusive bounds and an untruncated open start."""
    return funding.rates(self.shared, self.symbol, start, end)

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    """Read this account's settled funding on the contract within inclusive bounds.

    Positive amounts were received. Walks one-day windows, each a single page.
    """
    return funding.payments(self.shared, self.symbol, start, end)

  async def perp_position(self, *, ttl: timedelta | None = None) -> PerpPosition:
    """The one-way position in base units, from the account-wide position list."""
    rows = await self.shared.positions(ttl=ttl)
    return perp_position(position_row(rows, self.symbol), self.multiplier)

  async def perp_collateral(self, *, ttl: timedelta | None = None) -> PerpCollateral:
    """The bucket backing this contract: the cross pool of its settlement currency, or
    an open isolated position's own margin."""
    rows = await self.shared.positions(ttl=ttl)
    row = position_row(rows, self.symbol)
    if row is not None and row['currentQty'] != 0 and not row['crossMode']:
      return isolated_collateral(row)
    else:
      account = await self.shared.futures_account(await self.settle_currency(), ttl=ttl)
      return cross_collateral(account, rows)

  async def collateral_id(self) -> str:
    """The USDT futures pool, `<account_id>:perp`, separate from the spot wallet.

    Raises:
      NotImplementedError: The contract settles in another currency (USDC), whose
        futures balance is a second pool the exchange ID cannot name.
    """
    if await self.settle_currency() == POOL_CURRENCY:
      return f'{self.account_id}:perp'
    else:
      raise NotImplementedError(
        f'KuCoin {self.symbol} settles outside the USDT futures pool'
      )

  async def leverage(self, *, ttl: timedelta | None = None) -> Decimal:
    """The contract's cross-margin leverage setting."""

    async def fetch() -> Decimal:
      """One signed request for the symbol's setting."""
      row = await self.shared.call(
        lambda: self.client.futures.positions.get_cross_margin_leverage(self.symbol)
      )
      return row['leverage']

    value = await self.shared.reads.read(('leverage', self.symbol), fetch, ttl=ttl)
    self.shared.leverages[self.symbol] = order_leverage(value)
    return value

  async def set_leverage(self, leverage: Decimal):
    """Set the contract's cross-margin leverage (`changeCrossUserLeverage`).

    Raises:
      ValueError: `leverage` is not a positive whole number.
      ApiError: KuCoin answered that the change was not applied.
    """
    value = whole_leverage(leverage)
    applied = await self.shared.call(
      lambda: self.client.futures.positions.modify_cross_margin_leverage(
        self.symbol, leverage=Decimal(value)
      )
    )
    self.shared.reads.forget(('leverage', self.symbol))
    if not applied:
      raise ApiError(f'KuCoin did not change the {self.symbol} leverage')
    self.shared.leverages[self.symbol] = value

  async def order_leverage(self) -> int:
    """The leverage sent with each order: the cached cross setting, read once."""
    if (value := self.shared.leverages.get(self.symbol)) is not None:
      return value
    else:
      return order_leverage(await self.leverage(ttl=timedelta(seconds=0)))

  async def submit(self, order: NativeOrder) -> OrderResponse:
    """Place one cross-margin order; an IOC is read back once for what it filled.

    KuCoin acknowledges futures orders before matching them. An IOC read back as done
    with nothing filled is refused; a read that fails or finds it still open leaves
    `filled_qty` unknown. Resting orders are not read back.
    """
    request = perp_request(
      self.symbol,
      order,
      multiplier=self.multiplier,
      leverage=await self.order_leverage(),
    )
    ack = await self.shared.call(lambda: self.client.futures.orders.add(request))
    response = OrderResponse(id=ack['orderId'], details=ack)
    if order.time_in_force == 'IOC':
      try:
        row = await self.shared.call(
          lambda: self.client.futures.orders.get_by_order_id(ack['orderId'])
        )
      except Error:
        return response
      if row['status'] == 'done' and row['filledSize'] == 0:
        raise OrderRejected(f'Order {ack["orderId"]} ended with nothing filled', row)
      elif row['status'] == 'done':
        response.filled_qty = row['filledSize'] * self.multiplier
    return response

  async def place_batch(
    self, orders: Sequence[Order]
  ) -> Sequence[OrderResponse | Exception]:
    """Place up to 20 orders in one request (acknowledged, not yet matched)."""
    rules = await self.rules()
    leverage = await self.order_leverage()
    checked: list[NativeOrder | Exception] = []
    for order in orders:
      try:
        native = native_order(order, rules)
        perp_request(self.symbol, native, multiplier=self.multiplier, leverage=leverage)
        checked.append(native)
      except ValueError as exc:
        checked.append(exc)
    natives = [n for n in checked if isinstance(n, NativeOrder)]
    replies = iter(await self.send_batch(natives, leverage) if natives else [])
    return [next(replies) if isinstance(n, NativeOrder) else n for n in checked]

  async def send_batch(
    self, orders: Sequence[NativeOrder], leverage: int
  ) -> Sequence[OrderResponse | Exception]:
    """Send validated orders in one batch request."""
    requests: list[FuturesAddOrderLimit | FuturesAddOrderMarket] = [
      perp_request(self.symbol, n, multiplier=self.multiplier, leverage=leverage)
      for n in orders
    ]
    try:
      rows = await self.shared.call(
        lambda: self.client.futures.orders.batch_add(requests)
      )
    except Error as exc:
      return [refusal(exc) if refused(exc) else exc] * len(orders)
    return [batch_placed(r) for r in rows]

  def cancel(self, id: str):
    """Cancel by order ID; KuCoin processes it asynchronously."""
    return self.client.futures.orders.cancel_by_order_id(id)

  async def cancel_orders(
    self, ids: Sequence[str], *, settings: Settings = {}
  ) -> Sequence[FuturesBatchCancelResult | Exception]:
    """Cancel in native batches of ten: per order, its acknowledgement or its error."""
    results: list[FuturesBatchCancelResult | Exception] = []
    for offset in range(0, len(ids), BATCH_CANCEL):
      batch = list(ids[offset : offset + BATCH_CANCEL])
      rows = await self.shared.call(
        lambda: self.client.futures.orders.batch_cancel(batch)
      )
      results.extend(batch_cancelled(r) for r in rows)
    return results

  async def cancel_open_orders(self, *, settings: Settings = {}) -> Any:
    """Cancel every open (non-stop) order on this contract in one request."""
    return await self.shared.call(
      lambda: self.client.futures.orders.cancel_all(self.symbol)
    )

  async def fetch_order(self, id: str) -> OrderState | None:
    """Read one order; `None` when it belongs to another contract."""
    row = await self.shared.call(lambda: self.client.futures.orders.get_by_order_id(id))
    if row['symbol'] == self.symbol:
      return perp_order_state(row, self.multiplier)

  async def open_orders(self) -> Sequence[OrderState]:
    """Read this contract's active orders, every page."""
    pages = self.client.futures.orders.get_order_list_paged(
      'active', symbol=self.symbol
    )
    return [
      perp_order_state(r, self.multiplier)
      async for page in pages.via(self.shared.call)
      for r in page
    ]

  def event_trade(self, event: OrderEvent) -> Trade | None:
    """A fill of this contract from the futures order channel, in base units."""
    row = cast(FuturesOrderEvent, event)
    if row['symbol'] == self.symbol:
      return perp_event_trade(row, self.multiplier)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Read this contract's fills (trades, liquidations, ADL) within inclusive bounds.

    Walks seven-day windows up to now; KuCoin keeps three months.
    """
    if start.utcoffset() is None or end.utcoffset() is None:
      raise ValueError('Trade history bounds must be timezone-aware')
    return PaginatedResponse(self.trade_pages(start, end))

  async def trade_pages(
    self, start: datetime, end: datetime
  ) -> AsyncIterator[Sequence[Trade]]:
    """Page each window, retrying each page, each fill once."""
    seen: set[str] = set()
    for lower, upper in windows(start, end, datetime.now(timezone.utc)):
      pages = self.client.futures.orders.get_trade_history_paged(
        symbol=self.symbol, start_at=lower, end_at=upper, page_size=TRADES_PAGE
      )
      async for rows in pages.via(self.shared.call):
        fresh = [
          r
          for r in rows
          if r['tradeType'] in FILL_TYPES
          and lower <= r['createdAt'] <= upper
          and r['tradeId'] not in seen
        ]
        seen.update(r['tradeId'] for r in fresh)
        if fresh:
          yield [perp_trade(r, self.multiplier) for r in fresh]
