"""The perpetual Market object; market ids are the venue's numeric `market_id`."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from typing_extensions import Any, AsyncContextManager, AsyncIterable, Sequence
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
  Rules,
  Settings,
  Trade,
)

from ..core import COLLATERAL, FUNDING_INTERVAL, listed, random_client_order_id
from . import account, books, history, orders
from .common import Public

BPS = Decimal(10_000)


@dataclass(frozen=True, kw_only=True)
class RisexPerpMarket(Public, PerpMarket):
  """A USDC-margined perpetual market, on the account's cross margin."""

  index_id: int
  """The venue's numeric `market_id` (`1` is BTC/USDC)."""
  CANDLE_INTERVALS = history.CANDLE_INTERVALS

  @property
  def market_id(self) -> str:
    """The venue's `market_id`, as a decimal string."""
    return str(self.index_id)

  @property
  def exchange_id(self) -> str:
    """The perpetual exchange."""
    return 'perp'

  async def depth(self, *, levels: int | None = None, settings: Settings = {}) -> Book:
    """The aggregated REST book, at most 250 levels per side, with no timestamp.

    Args:
      levels: Keep at most this many levels per side.
      settings: Unused: RISEx has no depth settings.
    """
    return await books.depth(self.shared, self.index_id, levels=levels)

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """Maintain the book from the venue's snapshot and per-block level updates,
    stamped with each frame's `worker_timestamp`. Consumers of one market share a
    single upstream, on a connection of its own.

    Args:
      levels: Keep at most this many levels per side.
      queue_size: Books buffered for this subscriber.
      overflow: What to do when the buffer is full.
      settings: Unused: RISEx has no depth settings.
    """
    return books.depth_stream(
      self.shared,
      self.index_id,
      levels=levels,
      queue_size=queue_size,
      overflow=overflow,
    )

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Tick (`step_price`), step (`step_size`) and minimum size from the market's
    configuration; the fee schedule is served to logged-in accounts only, so `fees` is
    `None`. `api` is listed (`active` and unlocked) and not reduce-only. The
    undocumented `match_price_band` (a placement too far from the mark reverts with
    `OrderPriceOutsideMatchBand`), the leverage cap and the position cap stay in
    `details`."""
    m = await self.shared.market(self.index_id, refetch=refetch)
    config = m['config']
    return Rules(
      fee_asset=COLLATERAL,
      tick_size=config['step_price'],
      step_size=config['step_size'],
      fixed_min_qty=config['min_order_size'],
      fees=None,
      api=listed(m) and not m['reduce_only'],
      details={
        'name': config['name'],
        'active': m['active'],
        'unlocked': config['unlocked'],
        'post_only': m['post_only'],
        'reduce_only': m['reduce_only'],
        'max_leverage': config['max_leverage'],
        'match_price_band': config['match_price_band'],
        'max_position_size': m['max_position_size'],
        'open_interest_limit': config['open_interest_limit'],
      },
    )

  async def fees(self, *, refetch: bool = False) -> Fees:
    """The account's current tier rates (`account.fees`), one maker and one taker rate
    for every market and side; a negative maker rate is a rebate.

    Raises:
      AuthError: The client has no key to log in with (an address alone).
    """
    self.shared.require_keys()
    row = await self.shared.call(self.shared.client.account.fees)
    # The bps are declared `float`; `str()` gives back the venue's decimal (`-0.5`).
    return Fees.symmetric(
      maker=Decimal(str(row['maker_bps'])) / BPS,
      taker=Decimal(str(row['taker_bps'])) / BPS,
    )

  def candles(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> PaginatedResponse[Candle]:
    """Trade candles opening in `[start, end)`, oldest first; volume in the base asset,
    no quote volume or trade count."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(
      history.candles(self.shared, self.index_id, interval, start, end)
    )

  async def query_order(self, id: str) -> OrderState | None:
    """Look an order up by id, open or closed."""
    return await orders.query_order(self.shared, self.index_id, id)

  async def open_orders(self) -> Sequence[OrderState]:
    """The account's resting orders in the market, with their fill progress."""
    return await orders.open_orders(self.shared, self.index_id)

  def random_client_order_id(self) -> str:
    """A random decimal integer below `2^63`, sent as the order's `client_order_id`."""
    return random_client_order_id()

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Sign and send an order: `LIMIT` rests until cancelled, `POST_ONLY` adds
    `post_only`, `MARKET` is an immediate-or-cancel limit at `price`.

    `client_order_id` must be a non-negative decimal integer. `filled_qty` is reported
    for `MARKET` orders only.

    Raises:
      AuthError: The client has no signer key.
      ValueError: Zero size, non-positive or off-grid price or size, or a client order
        id that is not a decimal integer.
      OrderRejected: The venue refused the order (a crossing post-only reverts with
        `PostOnlyOrderMatched()`): nothing rests.
    """
    market = await self.shared.market(self.index_id)
    return await orders.place_order(self.shared, market, order)

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """Cancel by id; the reply is the mined transaction.

    Raises:
      OrderNotFound: The order no longer rests.
    """
    return await orders.cancel_order(self.shared, self.index_id, id)

  async def cancel_open_orders(self, *, settings: Settings = {}) -> Any:
    """Cancel every resting order of the account in the market, in one transaction."""
    return await orders.cancel_open_orders(self.shared, self.index_id)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """The account's fills, newest first, fees in USDC."""
    return PaginatedResponse(
      history.trades_history(self.shared, self.index_id, start, end)
    )

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """The account's new fills on this market, from the signer-authenticated `fills`
    stream, which every market of the account shares.

    Raises:
      AuthError: The client has no signer key.
    """
    return history.trades_stream(
      self.shared, self.index_id, queue_size=queue_size, overflow=overflow
    )

  async def perp_position(self, *, ttl: timedelta | None = None) -> PerpPosition:
    """The signed position and entry price."""
    return await account.perp_position(self.shared, self.index_id, ttl=ttl)

  async def perp_collateral(self, *, ttl: timedelta | None = None) -> PerpCollateral:
    """The account's one cross bucket, whatever the market.

    Raises:
      NotImplementedError: The account holds an isolated position.
    """
    return await account.collateral(self.shared, ttl=ttl)

  async def collateral_id(self) -> str:
    """The account's cross pool, `<account_id>:perp`, for every market: RISEx has no
    spot exchange, and orders draw on the pool's free collateral."""
    return f'{self.account_id}:{self.exchange_id}'

  async def leverage(self, *, ttl: timedelta | None = None) -> Decimal:
    """The account's leverage on the market: its setting, else the market maximum."""
    return await account.leverage(self.shared, self.index_id, ttl=ttl)

  async def index(self, *, settings: Settings = {}) -> Decimal:
    """The market's oracle index price, past the venue's 5-minute cache."""
    return (await self.shared.fresh(self.index_id))['index_price']

  async def next_funding(self, *, ttl: timedelta | None = None) -> NextFunding:
    """The venue's estimate of the next hourly rate (positive when longs pay) and its
    time, from the `expected_funding_rate` stream."""
    await self.shared.market(self.index_id)
    rows = await self.shared.reads.read(
      ('expected_funding', self.index_id),
      lambda: self.shared.call(
        lambda: history.expected_funding(self.shared, [self.index_id])
      ),
      ttl=ttl,
    )
    row = rows[self.index_id]
    return NextFunding(
      rate=row['estimated_rate'],
      time=row['next_funding_time'],
      interval=FUNDING_INTERVAL,
    )

  def funding_rates(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> PaginatedResponse[FundingRate]:
    """Applied hourly rates, newest first, with inclusive bounds."""
    return PaginatedResponse(
      history.funding_rates(self.shared, self.index_id, start, end)
    )

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    """The account's hourly funding on the market, inclusive bounds, positive when
    received, in USDC.

    Raises:
      ValueError: A bound is not timezone-aware.
    """
    return PaginatedResponse(
      history.funding_payments(self.shared, self.index_id, start, end)
    )
