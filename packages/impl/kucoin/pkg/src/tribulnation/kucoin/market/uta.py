"""Spot pairs and linear perpetuals on a KuCoin Unified Trading Account (UTA).

Public data is the Classic markets' own; every account read, order and fill goes through
the UTA REST V2 API (one endpoint per action, the product line chosen by `tradeType`)
and the UTA private WebSocket. Spot quantities are base units; futures quantities are
whole contracts on the wire, base units in the SDK.

References:
  - [UTA REST V2](https://www.kucoin.com/docs-new/v2/rest/ua/introduction)
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing_extensions import (
  Any,
  AsyncContextManager,
  AsyncIterable,
  AsyncIterator,
  Awaitable,
  Sequence,
  cast,
)

from typed_kucoin.schemas import UtaExecutionEvent
from typed_kucoin.uta.orders.batch_cancel import (
  UtaBatchCancelItem,
  UtaBatchCancelItemResult,
)
from tribulnation.sdk.core import (
  Error,
  LeverageNotSet,
  OrderRejected,
  OverflowPolicy,
  PaginatedResponse,
)
from tribulnation.sdk.market import (
  Fees,
  FundingPayment,
  Order,
  OrderResponse,
  OrderState,
  PerpCollateral,
  PerpPosition,
  Settings,
  SpotBalances,
  Trade,
)
from tribulnation.sdk.util import whole_leverage
from .common import POSITIONS_PAGE, OrderEvent
from .fills import connect_orders
from .native import NativeMarket, windows
from .orders import NativeOrder
from .perp import LinearPerpMarket
from .spot import SpotMarket
from . import unified

TRADES_PAGE = 200
"""Fills per page of the UTA fills endpoint (its maximum)."""
BATCH_CANCEL = 20
"""Most orders one UTA batch cancel takes."""
CANCEL_ALL = 100
"""Most orders one UTA cancel-all request cancels."""
FUNDING_WINDOW = timedelta(days=90)
"""The widest range the UTA funding history accepts."""
FUNDING_PAGE = 200
"""Settlements per page of the UTA funding history."""


class UtaOrders(NativeMarket):
  """Orders, fills and fees of either product line through the UTA API."""

  @property
  def trade_type(self) -> unified.TradeType:
    """The UTA `tradeType` of this market's product line."""
    return 'SPOT' if self.scope == 'spot' else 'FUTURES'

  async def fees(self, *, refetch: bool = False) -> Fees:
    """The account's actual rates on this symbol (VIP tier and market-maker program
    included; a maker rebate is a negative rate)."""
    rows = await self.shared.call(
      lambda: self.client.uta.account.fee_rate(self.trade_type, symbol=self.symbol)
    )
    return unified.fees(rows, self.symbol)

  async def submit(self, order: NativeOrder) -> OrderResponse:
    """Place one order; an IOC is read back once for what it filled.

    UTA acknowledges an order before matching it, on spot as on futures. An IOC read
    back as done with nothing filled is refused; a read that fails or finds it still
    open leaves `filled_qty` unknown. Resting orders are not read back, so a crossing
    post-only is acknowledged and then cancelled by the venue.
    """
    request = unified.order_request(
      self.symbol, order, trade_type=self.trade_type, multiplier=self.multiplier
    )
    ack = await self.shared.call(lambda: self.client.uta.orders.place(request))
    response = OrderResponse(id=ack['orderId'], details=ack)
    if order.time_in_force == 'IOC':
      try:
        row = await self.shared.call(
          lambda: self.client.uta.orders.detail(
            self.trade_type, symbol=self.symbol, order_id=ack['orderId']
          )
        )
      except Error:
        return response
      if unified.ended_unfilled(row):
        raise OrderRejected(f'Order {ack["orderId"]} ended with nothing filled', row)
      elif row['status'] in unified.DONE:
        response.filled_qty = row['filledSize'] * self.multiplier
    return response

  async def place_batch(
    self, orders: Sequence[Order]
  ) -> Sequence[OrderResponse | Exception]:
    """UTA REST has no batch placement: each order is placed on its own."""
    return await NativeMarket.place_batch(self, orders)

  def cancel(self, id: str) -> Awaitable[object]:
    """Cancel by order ID."""
    return self.client.uta.orders.cancel(
      self.trade_type, symbol=self.symbol, order_id=id
    )

  async def cancel_orders(
    self, ids: Sequence[str], *, settings: Settings = {}
  ) -> Sequence[Any]:
    """Cancel in native batches of 20: per order, its acknowledgement or its error."""
    results: list[UtaBatchCancelItemResult | Exception] = []
    for offset in range(0, len(ids), BATCH_CANCEL):
      batch: list[UtaBatchCancelItem] = [
        {'symbol': self.symbol, 'orderId': id}
        for id in ids[offset : offset + BATCH_CANCEL]
      ]
      reply = await self.shared.call(
        lambda: self.client.uta.orders.batch_cancel(
          self.trade_type, cancel_order_list=batch
        )
      )
      results.extend(unified.cancelled(r) for r in reply['items'])
    return results

  async def cancel_open_orders(self, *, settings: Settings = {}) -> Any:
    """Cancel every open (non-conditional) order on this symbol, 100 per request."""
    replies: list[Any] = []
    while True:
      reply = await self.shared.call(
        lambda: self.client.uta.orders.cancel_all(
          self.trade_type, symbol=self.symbol, order_filter='NORMAL'
        )
      )
      replies.append(reply)
      if len(reply['items']) < CANCEL_ALL:
        return replies

  async def fetch_order(self, id: str) -> OrderState | None:
    """Read one order; `None` when it belongs to another symbol.

    UTA keeps a cancelled order without fills readable for 2 hours, one with fills for
    168 hours.
    """
    row = await self.shared.call(
      lambda: self.client.uta.orders.detail(
        self.trade_type, symbol=self.symbol, order_id=id
      )
    )
    if row['symbol'] == self.symbol:
      return unified.order_state(row, self.multiplier)

  async def open_orders(self) -> Sequence[OrderState]:
    """Read this symbol's open (non-conditional) orders, every page."""
    states: list[OrderState] = []
    page = 1
    while True:
      reply = await self.shared.call(
        lambda: self.client.uta.orders.open_orders(
          self.trade_type,
          symbol=self.symbol,
          page_number=page,
          page_size=POSITIONS_PAGE,
        )
      )
      states.extend(unified.order_state(r, self.multiplier) for r in reply['items'])
      if len(reply['items']) < POSITIONS_PAGE:
        return states
      page += 1

  def event_trade(self, event: OrderEvent) -> Trade | None:
    """A position-changing fill of this symbol from the UTA `execution` channel.

    Pushes carry no product line, so a spot market also sees cross margin fills of its
    pair; this package places none.
    """
    row = cast(UtaExecutionEvent, event)
    if row['s'] == self.symbol and row.get('fT', 'NORMAL') in unified.FILL_TYPES:
      return unified.event_trade(row, self.multiplier)

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """Subscribe to this symbol's fills on the UTA `execution` channel.

    Fills carry the order and client order IDs, the liquidity role and the fee. One
    connection serves every market of the account; a dropped connection fails the
    stream with `NetworkError`, and subscribing again reconnects.
    """
    return self.shared.stream(
      'unified',
      lambda: connect_orders(self.shared, 'unified'),
      select=self.event_trade,
      queue_size=queue_size,
      overflow=overflow,
    )

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Read this symbol's fills (trades, liquidations, ADL) within inclusive bounds.

    Walks seven-day windows up to now, each by `lastId` cursor; each fill appears once.
    """
    if start.utcoffset() is None or end.utcoffset() is None:
      raise ValueError('Trade history bounds must be timezone-aware')
    return PaginatedResponse(self.trade_pages(start, end))

  async def trade_pages(
    self, start: datetime, end: datetime
  ) -> AsyncIterator[Sequence[Trade]]:
    """Page each window, retrying each page."""
    seen: set[str] = set()
    for lower, upper in windows(start, end, datetime.now(timezone.utc)):
      pages = self.client.uta.orders.trade_history_paged(
        self.trade_type,
        symbol=self.symbol,
        start_at=lower,
        end_at=upper,
        page_size=TRADES_PAGE,
      )
      async for rows in pages.via(self.shared.call):
        fresh = [
          r
          for r in rows
          if r['fillType'] in unified.FILL_TYPES
          and lower <= r['executionTime'] <= upper
          and r['tradeId'] not in seen
        ]
        seen.update(r['tradeId'] for r in fresh)
        if fresh:
          yield [unified.trade(r, self.multiplier) for r in fresh]


@dataclass(frozen=True, kw_only=True)
class UtaSpotMarket(UtaOrders, SpotMarket):
  """A spot pair on a Unified Trading Account."""

  async def balances(self, *, ttl: timedelta | None = None) -> SpotBalances:
    """The pair's base and quote balances in the unified account.

    `total` is the spot balance; `free` what spot orders can spend, which KuCoin reduces
    by unrealized futures losses (see `unified.balance`).
    """
    rules = await self.rules()
    account = await self.shared.uta_balance(ttl=ttl)
    return SpotBalances(
      base=unified.balance(account, rules.base),
      quote=unified.balance(account, rules.quote),
    )


@dataclass(frozen=True, kw_only=True)
class UtaPerpMarket(UtaOrders, LinearPerpMarket):
  """A linear perpetual on a Unified Trading Account: one-way, cross margin by default,
  margined by the account's one multi-asset pool."""

  async def perp_position(self, *, ttl: timedelta | None = None) -> PerpPosition:
    """The one-way position in base units, from the account-wide position list."""
    rows = await self.shared.uta_positions(ttl=ttl)
    return unified.perp_position(
      unified.position_row(rows, self.symbol), self.multiplier
    )

  async def perp_collateral(self, *, ttl: timedelta | None = None) -> PerpCollateral:
    """The unified pool (see `unified.unified_collateral`), or an open isolated
    position's own margin."""
    rows = await self.shared.uta_positions(ttl=ttl)
    row = unified.position_row(rows, self.symbol)
    if row is not None and row['size'] != 0 and row['marginMode'] == 'ISOLATED':
      return unified.isolated_collateral(row)
    else:
      return unified.unified_collateral(await self.shared.uta_overview(ttl=ttl), rows)

  async def collateral_id(self) -> str:
    """The unified pool, `<account_id>:perp`, for USDT- and USDC-settled contracts alike.

    UTA margins every cross position and new order from one multi-asset pool valued in
    USD (USDT, USDC and other enabled collateral at their collateral ratios); what new
    orders spend is that pool's available margin, not one currency's balance. So the ID
    names the pool, which `TradingMarkets.collateral` resolves to `perp_collateral()`.
    No request is made.
    """
    return f'{self.account_id}:perp'

  async def leverage(self, *, ttl: timedelta | None = None) -> Decimal:
    """The contract's cross leverage setting.

    Raises:
      LeverageNotSet: KuCoin reports no cross leverage for the contract.
    """

    async def fetch() -> Decimal:
      """One signed request for the contract's setting."""
      rows = await self.shared.call(
        lambda: self.client.uta.account.leverage(
          'FUTURES', symbol=self.symbol, margin_mode='CROSS'
        )
      )
      for row in rows:
        if (
          row.get('symbol', self.symbol) == self.symbol and row['marginMode'] == 'CROSS'
        ):
          return row['leverage']
      raise LeverageNotSet(f'KuCoin reports no cross leverage for {self.symbol}')

    return await self.shared.reads.read(('leverage', self.symbol), fetch, ttl=ttl)

  async def set_leverage(self, leverage: Decimal):
    """Set the contract's leverage (`/api/ua/v2/unified/account/modify-leverage`).

    Raises:
      ValueError: `leverage` is not a positive whole number.
      ApiError: KuCoin answered without the leverage it set.
    """
    value = whole_leverage(leverage)
    reply = await self.shared.call(
      lambda: self.client.uta.account.modify_leverage(
        self.symbol, leverage=Decimal(value)
      )
    )
    self.shared.reads.forget(('leverage', self.symbol))
    unified.check_leverage(reply.get('leverage'), self.symbol)

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    """Read this account's settled funding on the contract within inclusive bounds.

    Positive amounts were received. Walks 90-day windows, each by `lastId` cursor.
    """
    if start.utcoffset() is None or end.utcoffset() is None:
      raise ValueError('Funding history bounds must be timezone-aware')
    return PaginatedResponse(self.funding_pages(start, end))

  async def funding_pages(
    self, start: datetime, end: datetime
  ) -> AsyncIterator[Sequence[FundingPayment]]:
    """Page each window, retrying each page."""
    lower = start
    horizon = min(end, datetime.now(timezone.utc))
    while lower <= horizon:
      upper = min(lower + FUNDING_WINDOW - timedelta(milliseconds=1), horizon)
      pages = self.client.uta.positions.funding_history_paged(
        symbol=self.symbol, start_at=lower, end_at=upper, page_size=FUNDING_PAGE
      )
      async for rows in pages.via(self.shared.call):
        if payments := [
          FundingPayment(amount=r['fundingFee'], time=r['settlementTime'])
          for r in rows
          if r['symbol'] == self.symbol and lower <= r['settlementTime'] <= upper
        ]:
          yield payments
      lower = upper + timedelta(milliseconds=1)
