"""Binance USD-M futures market."""

from typing_extensions import (
  AsyncContextManager,
  AsyncIterable,
  Literal,
  Sequence,
)
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from tribulnation.sdk.core import OverflowPolicy, PaginatedResponse
from tribulnation.sdk.market import (
  PerpMarket as _PerpMarket,
  Book,
  FundingPayment,
  FundingRate,
  NextFunding,
  Order,
  OrderResponse,
  OrderState,
  PerpCollateral,
  PerpPosition,
  Rules,
  Settings,
  Trade,
)

from typed_binance.schemas import MarkPriceInfo
from typed_binance.usdm_futures.public_streams.partial_depth import PartialDepthEvent

from tribulnation.binance.util import windows

from .impl import (
  SharedMixin,
  wrap_exceptions,
  not_implemented,
  futures_permission_error,
)

REST_DEPTH_LEVELS: tuple[Literal[5, 10, 20, 50, 100, 500, 1000], ...] = (
  5,
  10,
  20,
  50,
  100,
  500,
  1000,
)
"""Depth values Binance's USD-M futures REST order book accepts (`limit`)."""

FUNDING_RATES_WINDOW = timedelta(days=30)
"""Window per `fundingRate` call. Comfortably under its 1000-row cap even at hourly funding."""

DEFAULT_STREAM_SPEED: Literal[100, 250, 500] = 100
"""Partial-depth push interval, in milliseconds."""


def rest_levels(levels: int | None) -> Literal[5, 10, 20, 50, 100, 500, 1000] | None:
  """Round `levels` up to the smallest depth the REST book actually serves."""
  if levels is None:
    return None
  for choice in REST_DEPTH_LEVELS:
    if choice >= levels:
      return choice
  return REST_DEPTH_LEVELS[-1]


def stream_levels(levels: int | None) -> Literal[5, 10, 20]:
  """Round `levels` up to the smallest depth the WS stream actually serves."""
  if levels is None or levels > 10:
    return 20
  if levels > 5:
    return 10
  return 5


def one_mark_price(
  response: MarkPriceInfo | list[MarkPriceInfo],
) -> MarkPriceInfo:
  """Unwrap `premium_index`, which answers with a list when no symbol is given."""
  if not isinstance(response, list):
    return response
  if not response:
    raise ValueError('premium_index returned no rows')
  return response[0]


@dataclass(frozen=True, kw_only=True)
class PerpMarket(SharedMixin, _PerpMarket):
  """A Binance USD-M futures market.

  Only the public endpoints (`depth`, `depth_stream`, `index`, `next_funding`,
  `funding_rates`) are implemented: every private USD-M Futures endpoint returned 401
  (`Invalid API-key, IP, or permissions`) against the tested account -- Binance blocks
  USD-M Futures for EEA accounts under MiCA. See `futures_permission_error`.
  """

  symbol: str

  @property
  def venue_id(self) -> str:
    return 'binance'

  @property
  def exchange_id(self) -> str:
    return 'usdm'

  @property
  def market_id(self) -> str:
    return self.symbol

  @wrap_exceptions
  async def depth(self, *, levels: int | None = None) -> Book:
    raw = await self.client.usdm_futures.http.market.depth(
      symbol=self.symbol, limit=rest_levels(levels)
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
        bids=[Book.Entry(Decimal(p), Decimal(q)) for p, q in event['b']],
        asks=[Book.Entry(Decimal(p), Decimal(q)) for p, q in event['a']],
      )

    return self.client.usdm_futures.public_streams.partial_depth(
      self.symbol.lower(),
      levels=stream_levels(levels),
      speed=DEFAULT_STREAM_SPEED,
    ).map(to_book)

  @wrap_exceptions
  async def index(self, *, settings: Settings = {}) -> Decimal:
    raw = await self.client.usdm_futures.http.market.premium_index(symbol=self.symbol)
    return one_mark_price(raw)['indexPrice']

  @wrap_exceptions
  async def next_funding(self) -> NextFunding:
    raw = await self.client.usdm_futures.http.market.premium_index(symbol=self.symbol)
    premium = one_mark_price(raw)
    info = await self.client.usdm_futures.http.market.funding_info()
    cfg = next((f for f in info if f['symbol'] == self.symbol), None)
    interval_hours = cfg['fundingIntervalHours'] if cfg else 8
    return NextFunding(
      rate=premium['lastFundingRate'],
      time=premium['nextFundingTime'],
      interval=timedelta(hours=interval_hours),
    )

  @PaginatedResponse.lift
  async def funding_rates(
    self, start: datetime | None = None, end: datetime | None = None
  ):
    """Fetch historical funding rates.

    With both bounds, walks the range one 30-day page at a time; with either omitted,
    makes a single call, matching the venue's own "most recent 200" behavior for an
    unbounded query.
    """
    if start is None or end is None:
      raw = await self.call_binance(
        lambda: self.client.usdm_futures.http.market.funding_rate(
          symbol=self.symbol, start_time=start, end_time=end, limit=1000
        )
      )
      if raw:
        yield [FundingRate(rate=r['fundingRate'], time=r['fundingTime']) for r in raw]
      return
    for window_start, window_end in windows(start, end, FUNDING_RATES_WINDOW):
      raw = await self.call_binance(
        lambda: self.client.usdm_futures.http.market.funding_rate(
          symbol=self.symbol,
          start_time=window_start,
          end_time=window_end,
          limit=1000,
        )
      )
      if raw:
        yield [FundingRate(rate=r['fundingRate'], time=r['fundingTime']) for r in raw]

  async def rules(self, *, refetch: bool = False) -> Rules:
    raise futures_permission_error('rules', self.id)

  async def open_orders(self) -> Sequence[OrderState]:
    raise futures_permission_error('open_orders', self.id)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    raise futures_permission_error('trades_history', self.id)

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    raise futures_permission_error('trades_stream', self.id)

  async def available_notional(self) -> Decimal:
    raise futures_permission_error('available_notional', self.id)

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    raise not_implemented('place_order', self.id)

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> object:
    raise not_implemented('cancel_order', self.id)

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    raise futures_permission_error('funding_payments', self.id)

  async def perp_position(self) -> PerpPosition:
    raise futures_permission_error('perp_position', self.id)

  async def perp_collateral(self) -> PerpCollateral:
    raise futures_permission_error('perp_collateral', self.id)
