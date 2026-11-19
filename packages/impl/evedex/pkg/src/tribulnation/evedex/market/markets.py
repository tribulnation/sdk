"""The perpetual Market object; market ids are the venue's instrument names."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import asyncio

from typing_extensions import Any, AsyncContextManager, AsyncIterable, Sequence
from typed_evedex.schemas import Instrument, TradingFees, User
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
  PerpMarket,
  PerpPosition,
  RemainingPositionLimit,
  Rules,
  Settings,
  Trade,
)

from ..core import (
  COLLATERAL,
  DEFAULT_LEVERAGE,
  FUNDING_SETTLEMENT,
  random_client_order_id,
  tradable,
)
from . import account, books, history, orders
from .common import Public, signed

log = logging.getLogger(__name__)

NO_FUNDING_HISTORY = 'EVEDEX publishes no funding-rate history: only the current rate'
NO_FUNDING_PAYMENTS = (
  "EVEDEX funding payments are not supported: the account ledger's `fundingRate` "
  'entries name no instrument'
)


def index_price(row: Instrument) -> Decimal:
  """The instrument's index price: its base coin's `avgLastPrice` times `lotSize`."""
  return row['from']['avgLastPrice'] * row['lotSize']


def next_settlement(now: datetime) -> datetime:
  """The next whole UTC hour after `now`: EVEDEX settles funding hourly."""
  hour = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
  return hour + FUNDING_SETTLEMENT


def next_funding(row: Instrument, *, now: datetime) -> NextFunding:
  """The next hourly settlement: the current rate, computed every
  `fundingRateInterval` hours, pro-rated to one hour (EVEDEX's documented
  `FR / 8` per hourly settlement); positive when longs pay."""
  return NextFunding(
    rate=row['fundingRate'] / row['fundingRateInterval'],
    time=next_settlement(now),
    interval=FUNDING_SETTLEMENT,
  )


def account_fees(user: User) -> Fees:
  """The account's rates: its personal overrides where set, else the `tradingFees`
  that apply to it."""
  rates: TradingFees = user['tradingFees']
  personal = user['personalTradingFees'] or {}
  return Fees.symmetric(
    maker=personal.get('makerFee', rates['maker']),
    taker=personal.get('takerFee', rates['taker']),
  )


@dataclass(frozen=True, kw_only=True)
class EvedexPerpMarket(Public, PerpMarket):
  """A USDT-margined perpetual, on the account's one cross-margin balance."""

  name: str
  """The instrument's name (`BTCUSD`)."""
  CANDLE_INTERVALS = history.CANDLE_INTERVALS

  @property
  def market_id(self) -> str:
    """The instrument's name."""
    return self.name

  @property
  def exchange_id(self) -> str:
    """The perpetual exchange."""
    return 'perp'

  async def depth(self, *, levels: int | None = None, settings: Settings = {}) -> Book:
    """The aggregated REST book, at most 100 levels per side, stamped with its time.

    Args:
      levels: Keep at most this many levels per side.
      settings: Unused: EVEDEX has no depth settings.
    """
    return await books.depth(self.shared, self.name, levels=levels)

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """The venue's whole book on every publication, at most 100 levels per side.
    Consumers of one market share a single upstream.

    Args:
      levels: Keep at most this many levels per side.
      queue_size: Books buffered for this subscriber.
      overflow: What to do when the buffer is full.
      settings: Unused: EVEDEX has no depth settings.
    """
    return books.depth_stream(
      self.shared, self.name, levels=levels, queue_size=queue_size, overflow=overflow
    )

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Tick (`priceIncrement`), step (`quantityIncrement`), minimum and maximum
    quantity, minimum notional (`minVolume`) and the instrument's standard fee rates.
    `api` is open for every account (`trading` `all` or `schedule`, the session open
    and the matcher active). The relative price bounds are the mark-price band,
    `markPriceLimit` either side of the mark (±30% on most instruments; a buy 7% under
    the mark was accepted on mainnet, 2026-11-19). The absolute range the venue
    accepts now (`minPrice`/`maxPrice`) and the leverage tiers stay in `details`."""
    row = await self.shared.instrument(self.name, refetch=refetch)
    fees = row['fees']
    return Rules(
      fee_asset=COLLATERAL,
      tick_size=row['priceIncrement'],
      step_size=row['quantityIncrement'],
      fixed_min_qty=row['minQuantity'],
      min_value=row['minVolume'],
      max_qty=row['maxQuantity'],
      rel_min_price=1 - row['markPriceLimit'],
      rel_max_price=1 + row['markPriceLimit'],
      fees=Fees.symmetric(maker=fees['maker'], taker=fees['taker']),
      api=tradable(row),
      details={
        'type': row['type'],
        'trading': row['trading'],
        'marketState': row['marketState'],
        'matcherState': row['matcherState'],
        'minPrice': row['minPrice'],
        'maxPrice': row['maxPrice'],
        'markPriceLimit': row['markPriceLimit'],
        'maxLeverage': row['maxLeverage'],
        'leverageLimit': row['leverageLimit'],
        'lotSize': row['lotSize'],
      },
    )

  async def fees(self, *, refetch: bool = False) -> Fees:
    """The account's maker and taker rates, the same on every market and side.

    Raises:
      AuthError: The client is public.
    """
    user = await account.me(self.shared, ttl=None)
    return account_fees(user)

  def candles(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> PaginatedResponse[Candle]:
    """Trade candles opening in `[start, end)`, from the venue's newest-first walk;
    volume in the base asset and the quote coin (USD)."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(
      history.candles(self.shared, self.name, interval, start, end)
    )

  async def query_order(self, id: str) -> OrderState | None:
    """Look an order up by id, open or closed."""
    return await orders.query_order(self.shared, self.name, id)

  async def open_orders(self) -> Sequence[OrderState]:
    """The account's open orders on the market, with their fill progress."""
    return await orders.open_orders(self.shared, self.name)

  def random_client_order_id(self) -> str:
    """A fresh venue order id (`DDDDD:<26 hex>`), sent as the order's own id."""
    return random_client_order_id()

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Sign and send a limit order at the account's leverage on the market: `LIMIT`
    rests until cancelled, `MARKET` is an immediate-or-cancel limit at `price`.
    `POST_ONLY` is not supported: the venue refuses `postOnly`.

    `client_order_id` becomes the order's id, so it must be a venue order id
    (`random_client_order_id()`). `filled_qty` is `None`: the venue accepts orders
    before executing them.

    Raises:
      NotImplementedError: A `POST_ONLY` order.
      AuthError: The client has no wallet key.
      ValueError: Zero size, non-positive or off-grid price or size, or a client order
        id that is not a venue order id.
      OrderRejected: The venue refused the order: nothing rests.
    """
    row, leverage = await asyncio.gather(
      self.shared.instrument(self.name),
      account.leverage(self.shared, self.name, ttl=None),
    )
    return await orders.place_order(self.shared, row, order, leverage=leverage)

  async def replace_order(
    self, id: str, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Cancel `id`, then place `order` (the SDK default; the venue's `replace_limit` is
    not mapped). A `POST_ONLY` replacement is refused before `id` is cancelled.

    Raises:
      NotImplementedError: A `POST_ONLY` order; `id` still rests.
    """
    if order['type'] == 'POST_ONLY':
      raise NotImplementedError(orders.POST_ONLY_REFUSED)
    return await super().replace_order(id, order, settings=settings)

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """Cancel by id.

    Raises:
      OrderNotFound: The venue does not know the id.
    """
    return await orders.cancel_order(self.shared, id)

  async def cancel_open_orders(self, *, settings: Settings = {}) -> Any:
    """Cancel every open order of the account on the market, in one request."""
    return await orders.cancel_open_orders(self.shared, self.name)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """The account's fills, with their fees in USDT (`usdt`)."""
    return PaginatedResponse(history.trades_history(self.shared, self.name, start, end))

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """The account's new fills on this market, from the wallet-authenticated
    `orderFills` channel, which every market shares; fills carry no fee.

    Raises:
      AuthError: The client has no wallet key.
    """
    return history.trades_stream(
      self.shared, self.name, queue_size=queue_size, overflow=overflow
    )

  async def perp_position(self, *, ttl: timedelta | None = None) -> PerpPosition:
    """The signed position and entry price."""
    return await account.perp_position(self.shared, self.name, ttl=ttl)

  async def perp_collateral(self, *, ttl: timedelta | None = None) -> PerpCollateral:
    """The account's one cross bucket, whatever the market."""
    return await account.collateral(self.shared, ttl=ttl)

  async def collateral_id(self) -> str:
    """The account's cross pool, `<account_id>:perp`, for every market."""
    return f'{self.account_id}:{self.exchange_id}'

  async def leverage(self, *, ttl: timedelta | None = None) -> Decimal:
    """The account's leverage setting on the market, 1 where never set."""
    return Decimal(await account.leverage(self.shared, self.name, ttl=ttl))

  async def set_leverage(self, leverage: Decimal):
    """Set the account's leverage on the market; the next `leverage()` reads it.

    Raises:
      ValueError: `leverage` is not a positive whole number, or is above the market's
        `maxLeverage`.
      AuthError: The client is public.
    """
    await account.set_leverage(self.shared, self.name, leverage)
    log.info('%s: leverage set to %s', self.id, leverage)

  async def remaining_position_limit(
    self, *, ttl: timedelta | None = None
  ) -> RemainingPositionLimit:
    """The instrument's `leverageLimit` notional at the account's leverage, less the
    position held in each direction, at the mark price.

    Raises:
      NotImplementedError: The account has its own leverage limits.
    """
    row, user, rows = await asyncio.gather(
      self.shared.call(
        lambda: self.shared.client.exchange.market.instrument(self.name)
      ),
      account.me(self.shared, ttl=ttl),
      account.positions(self.shared, ttl=ttl),
    )
    p = account.record(rows, self.name)
    return account.remaining_position_limit(
      row,
      user=user,
      size=Decimal(0) if p is None else signed(p['side'], p['quantity']),
      leverage=DEFAULT_LEVERAGE if p is None else p['leverage'],
    )

  async def index(self, *, settings: Settings = {}) -> Decimal:
    """The instrument's index price: its base coin's `avgLastPrice` times `lotSize`."""
    row = await self.shared.call(
      lambda: self.shared.client.exchange.market.instrument(self.name)
    )
    return index_price(row)

  async def next_funding(self, *, ttl: timedelta | None = None) -> NextFunding:
    """The next hourly settlement: the instrument's current rate (computed every 8
    hours) pro-rated to one hour, at the next whole hour; positive when longs pay."""
    row = await self.shared.reads.read(
      ('instrument', self.name),
      lambda: self.shared.call(
        lambda: self.shared.client.exchange.market.instrument(self.name)
      ),
      ttl=ttl,
    )
    return next_funding(row, now=datetime.now(timezone.utc))

  def funding_rates(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> PaginatedResponse[FundingRate]:
    """Not supported: EVEDEX publishes only the current rate."""
    raise NotImplementedError(NO_FUNDING_HISTORY)

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    """Not supported: the account ledger's funding entries name no instrument."""
    raise NotImplementedError(NO_FUNDING_PAYMENTS)
