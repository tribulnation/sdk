"""One Kraken linear perpetual: public data, and with a Futures key, its account,
orders and feeds."""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import asyncio
import uuid
from typing_extensions import (
  Any,
  AsyncContextManager,
  AsyncIterable,
  AsyncIterator,
  Sequence,
  cast,
)

from tribulnation.sdk.core import OverflowPolicy, PaginatedResponse
from tribulnation.sdk.market import (
  Book,
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
  PerpMarket as BasePerpMarket,
  PerpPosition,
  Rules,
  Settings,
  Trade,
  detached_books,
)
from typed_kraken.futures.instruments import FuturesInstrument
from typed_kraken.futures_trading.ws import WsFill

from .impl import SharedMixin
from .impl.futures_state import FuturesState
from .impl import perp_orders
from .impl.perp_account import (
  fees_of,
  funding_payment,
  leverage_of,
  open_order_state,
  parse_fill,
  position,
  status_state,
)
from .impl.perp_candles import CANDLE_INTERVALS, candles
from .impl.perp_data import is_market_ticker, parse_book, parse_rules
from .impl.perp_pool import pool_collateral
from .impl.perp_streams import parse_ws_fill

FUNDING_INTERVAL = timedelta(hours=1)
FEES_TTL = timedelta(hours=1)
"""Fee tiers follow 30-day volume, so an hour-old answer is current enough."""
FILLS_PAGE = 100
"""Rows `GET /fills` answers per request."""


def next_hour(now: datetime) -> datetime:
  """The next full hour after `now`, when funding settles."""
  return now.replace(minute=0, second=0, microsecond=0) + FUNDING_INTERVAL


@dataclass(frozen=True, kw_only=True)
class PerpMarket(SharedMixin, BasePerpMarket):
  """A unit-size linear perpetual (`PF_`) on the multi-collateral account.

  Quantities are contracts, which are base units. Orders and account reads need the
  account's Futures API key; without one, only public data works.

  Settings, under `settings['kraken']` (see `KrakenSettings`):
  `{'time_in_force': 'ioc'}` sends a `LIMIT` as immediate-or-cancel (`'post'`:
  post-only), and `{'reduce_only': True}` only reduces the position.
  """

  symbol: str
  CANDLE_INTERVALS = CANDLE_INTERVALS

  @property
  def exchange_id(self) -> str:
    """Linear perpetuals use the existing perp exchange ID."""
    return 'perp'

  @property
  def market_id(self) -> str:
    """Keep the exact case and spelling of the instrument symbol."""
    return self.symbol

  @property
  def perp(self) -> FuturesState:
    """The account's Futures client and shared state."""
    return self.shared.perp

  def owns(self, symbol: str) -> bool:
    """Whether a row's symbol is this market's; Kraken answers in either case."""
    return symbol.upper() == self.symbol.upper()

  async def depth(self, *, levels: int | None = None, settings: Settings = {}) -> Book:
    """Fetch the full public book, sort by price, and trim to the requested depth."""
    if levels is not None and levels < 1:
      raise ValueError('levels must be positive')
    response = await self.call_kraken(
      lambda: self.client.futures.orderbook(self.symbol)
    )
    return parse_book(response['orderBook'], levels=levels)

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """The full book from the public `book` feed, trimmed to `levels`."""

    @asynccontextmanager
    async def stream():
      """Subscribe to the shared feed and detach each book."""
      async with self.perp.book(self.symbol).subscribe(
        queue_size=queue_size, overflow=overflow
      ) as books:
        yield detached_books(books, levels)

    return stream()

  async def instrument(self, *, refetch: bool = False) -> FuturesInstrument:
    """The market's qualified instrument row."""
    row = (await self.shared.load_perps(refetch=refetch)).get(self.symbol)
    if row is None:
      raise ValueError(f'Kraken perpetual is no longer qualified: {self.symbol}')
    return row

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Read public precision constraints and the native USD fee asset."""
    row = await self.instrument(refetch=refetch)
    return parse_rules(row, fee_asset=await self.shared.load_fee_asset())

  async def fees(self, *, refetch: bool = False) -> Fees:
    """The account's tier of the market's fee schedule, by its 30-day volume."""
    trading = self.perp.client.trading
    ttl = None if refetch else FEES_TTL
    instrument, schedules, volumes = await asyncio.gather(
      self.instrument(),
      self.perp.read('fee_schedules', trading.fee_schedules, ttl=ttl),
      self.perp.read('fee_volumes', trading.fee_volumes, ttl=ttl),
    )
    return fees_of(instrument, schedules, volumes)

  def candles(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> PaginatedResponse[Candle]:
    """Return native trade candles inside aware half-open bounds."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(candles(self.shared, self.symbol, interval, start, end))

  async def ticker(self):
    """The contract's public ticker."""
    response = await self.call_kraken(lambda: self.client.futures.ticker(self.symbol))
    row = response['ticker']
    if not is_market_ticker(row):
      raise ValueError('Kraken returned an index ticker instead of a contract ticker')
    return row

  async def index(self, *, settings: Settings = {}) -> Decimal:
    """Read the contract's own index price from its public ticker."""
    return Decimal(str((await self.ticker())['indexPrice']))

  async def next_funding(self, *, ttl: timedelta | None = None) -> NextFunding:
    """The current hour's relative rate (`relativeFundingRate`), settled at the next
    full hour.

    Kraken's `fundingRate` is absolute (USD per contract per hour); the relative rate
    is the fraction of notional per hour, the SDK's unit. The latest
    `funding_rates` row is the same rate.
    """
    row = await self.ticker()
    if (rate := row.get('relativeFundingRate')) is None:
      raise ValueError(f'Kraken ticker has no relative funding rate: {self.symbol}')
    return NextFunding(
      rate=Decimal(str(rate)),
      time=next_hour(datetime.now(timezone.utc)),
      interval=FUNDING_INTERVAL,
    )

  def funding_rates(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> PaginatedResponse[FundingRate]:
    """Return relative rates at documented hourly settlement times.

    Kraken timestamps the start of the accrual period. SDK payment time is one
    hour later. Filter after that conversion, preserving inclusive/open bounds.

    References:
      - https://support.kraken.com/in/articles/4844359082772-linear-multi-collateral-derivatives-contract-specifications
    """
    if any(bound is not None and bound.utcoffset() is None for bound in (start, end)):
      raise ValueError('Funding bounds must be timezone-aware')
    if start is not None and end is not None and end < start:
      raise ValueError('Funding end must not precede start')

    async def pages():
      """Fetch the retained native history once through the per-request retry seam."""
      response = await self.call_kraken(
        lambda: self.client.futures.historical_funding_rates(self.symbol)
      )
      page: list[FundingRate] = []
      for row in response['rates']:
        settlement = row['timestamp'] + FUNDING_INTERVAL
        if (start is None or start <= settlement) and (
          end is None or settlement <= end
        ):
          page.append(
            FundingRate(time=settlement, rate=Decimal(str(row['relativeFundingRate'])))
          )
      yield page

    return PaginatedResponse(pages())

  async def open_orders(self) -> Sequence[OrderState]:
    """This market's open orders."""
    result = await self.call_kraken(self.perp.client.trading.open_orders)
    return [open_order_state(r) for r in result['openOrders'] if self.owns(r['symbol'])]

  async def query_order(self, id: str) -> OrderState | None:
    """An open or recently closed order of this market, by ID (`orders/status`)."""
    result = await self.call_kraken(lambda: self.perp.client.trading.order_status([id]))
    for entry in result['orders']:
      if entry['order']['orderId'] == id and self.owns(entry['order']['symbol']):
        return status_state(entry)

  @PaginatedResponse.lift
  async def trades_history(
    self, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Trade]]:
    """This market's fills within inclusive bounds, newest first, without fees.

    `GET /fills` answers the account's last 100 fills up to a time; pages walk back
    from `end` until they pass `start`.
    """
    cursor, seen = end, set[str]()
    while True:
      before = cursor
      page = await self.call_kraken(lambda: self.perp.client.trading.fills(before))
      rows = [r for r in page['fills'] if r['fill_id'] not in seen]
      seen.update(r['fill_id'] for r in rows)
      if trades := [
        parse_fill(r)
        for r in rows
        if self.owns(r['symbol']) and start <= r['fillTime'] <= end
      ]:
        yield trades
      if not rows or len(page['fills']) < FILLS_PAGE:
        return
      cursor = min(r['fillTime'] for r in rows)
      if cursor < start:
        return

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """This market's fills, with fees, from the account's shared `fills` feed."""

    async def parsed(fills: AsyncIterable[WsFill]) -> AsyncIterator[Trade]:
      """Keep this market's fills."""
      async for fill in fills:
        if self.owns(fill['instrument']):
          yield parse_ws_fill(fill)

    @asynccontextmanager
    async def stream():
      """Subscribe to the shared feed."""
      async with self.perp.fills_feed().subscribe(
        queue_size=queue_size, overflow=overflow
      ) as fills:
        yield parsed(fills)

    return stream()

  def random_client_order_id(self) -> str:
    """A fresh UUID, the form Kraken's `cliOrdId` takes."""
    return str(uuid.uuid4())

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Place a `LIMIT` (`lmt`), `POST_ONLY` (`post`) or `MARKET` (`ioc` at `price`).

    `filled_qty` is what filled on arrival; final for IOC and `MARKET` orders.

    Raises:
      OrderRejected: Kraken did not place it: a post-only that would cross, an IOC
        with nothing to fill, insufficient funds, an invalid price or size, ...
    """
    return await perp_orders.place_order(self, order, settings=settings)

  async def place_orders(
    self, orders: Sequence[Order], *, settings: Settings = {}
  ) -> Sequence[OrderResponse | Exception]:
    """Place several orders in one `batchorder`; one result per order."""
    return await perp_orders.place_orders(self, orders, settings=settings)

  async def replace_order(
    self, id: str, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Edit `id` in place to `order`'s price and size; see `perp_orders.replace_order`."""
    return await perp_orders.replace_order(self, id, order, settings=settings)

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """Cancel one order; `OrderNotFound` when it no longer rests."""
    return await perp_orders.cancel_order(self, id, settings=settings)

  async def cancel_orders(
    self, ids: Sequence[str], *, settings: Settings = {}
  ) -> Sequence[str | Exception]:
    """Cancel in one `batchorder`: per order, `cancelled` or its error."""
    return await perp_orders.cancel_orders(self, ids, settings=settings)

  async def cancel_open_orders(self, *, settings: Settings = {}) -> Any:
    """Cancel every open order of this market (`cancelallorders` by symbol)."""
    return await perp_orders.cancel_open_orders(self, settings=settings)

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    """This market's realized funding within bounds, from the account log."""

    async def pages():
      """One page of the log's funding rows."""
      result = await self.call_kraken(
        lambda: self.perp.client.trading.account_log(
          since=start, before=end, info='funding rate change'
        )
      )
      yield [
        payment
        for row in result['logs']
        if self.owns(row.get('contract') or '')
        and (payment := funding_payment(row)) is not None
        and start <= payment.time <= end
      ]

    return PaginatedResponse(pages())

  async def perp_position(self, *, ttl: timedelta | None = None) -> PerpPosition:
    """The position in this market, flat when there is none."""
    result = await self.perp.positions(ttl=ttl)
    return position(result['openPositions'], self.symbol)

  async def collateral_id(self) -> str:
    """The multi-collateral pool, `<account_id>:perp`, which funds every `PF_` market."""
    return f'{self.account_id}:perp'

  async def leverage(self, *, ttl: timedelta | None = None) -> Decimal:
    """Isolated markets' set leverage; cross markets' first-tier retail margin."""
    instrument, preferences = await asyncio.gather(
      self.instrument(), self.perp.leverage_preferences(ttl=ttl)
    )
    return leverage_of(
      instrument,
      preferences['leveragePreferences'],
      schedule=self.perp.margin_schedule,
    )

  async def set_leverage(self, leverage: Decimal) -> None:
    """Not supported: cross leverage on Kraken is the margin schedule's, not a setting.

    A leverage preference (`PUT /leveragepreferences`) would move the market to isolated
    margin, which the SDK never does on its own (ADR 0066).

    Raises:
      NotImplementedError: Always, before anything is sent.
    """
    raise NotImplementedError(
      f'Kraken cross leverage is set by the margin schedule; a leverage preference '
      f'would switch {self.symbol} to isolated margin [{self.id}]'
    )

  async def perp_collateral(self, *, ttl: timedelta | None = None) -> PerpCollateral:
    """The multi-collateral (cross) bucket; an isolated position's is not supported."""
    preferences = await self.perp.leverage_preferences(ttl=ttl)
    if any(self.owns(r['symbol']) for r in preferences['leveragePreferences']):
      raise NotImplementedError(
        f'Kraken isolated-margin collateral is not supported [{self.id}]'
      )
    return await pool_collateral(self.shared, ttl=ttl)
