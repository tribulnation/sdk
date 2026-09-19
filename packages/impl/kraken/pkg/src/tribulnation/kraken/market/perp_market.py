"""One Kraken linear perpetual's public REST market data."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing_extensions import Any, AsyncContextManager, AsyncIterable, Sequence

from tribulnation.sdk.core import OverflowPolicy, PaginatedResponse
from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
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
)
from .impl import SharedMixin
from .impl.perp_data import is_market_ticker, parse_book, parse_rules
from .impl.perp_candles import CANDLE_INTERVALS, candles


@dataclass(frozen=True, kw_only=True)
class PerpMarket(SharedMixin, BasePerpMarket):
  """Public data for a qualified unit-size linear perpetual; private methods are absent."""

  symbol: str
  CANDLE_INTERVALS = CANDLE_INTERVALS

  @property
  def venue_id(self) -> str:
    """Native symbols belong to the Kraken platform."""
    return 'kraken'

  @property
  def exchange_id(self) -> str:
    """Linear perpetuals use the existing perp exchange ID."""
    return 'perp'

  @property
  def market_id(self) -> str:
    """Keep the exact case and spelling of the instrument symbol."""
    return self.symbol

  async def depth(self, *, levels: int | None = None) -> Book:
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
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """Futures WebSocket books need their own typed subscription qualification."""
    raise NotImplementedError('Kraken Futures depth streams are not implemented')

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Read public precision constraints and the native USD fee asset."""
    row = (await self.shared.load_perps(refetch=refetch)).get(self.symbol)
    if row is None:
      raise ValueError(f'Kraken perpetual is no longer qualified: {self.symbol}')
    return parse_rules(row, fee_asset=await self.shared.load_fee_asset())

  def candles(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> PaginatedResponse[Candle]:
    """Return native trade candles inside aware half-open bounds."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(candles(self.shared, self.symbol, interval, start, end))

  async def index(self, *, settings: Settings = {}) -> Decimal:
    """Read the contract's own index price from its public ticker."""
    response = await self.call_kraken(lambda: self.client.futures.ticker(self.symbol))
    row = response['ticker']
    if not is_market_ticker(row):
      raise ValueError('Kraken returned an index ticker instead of a contract ticker')
    return Decimal(str(row['indexPrice']))

  async def next_funding(self) -> NextFunding:
    """The current native ticker lacks a qualified relative rate and settlement time."""
    raise NotImplementedError(
      'Kraken Futures next funding has no qualified native rate/time mapping'
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
        settlement = row['timestamp'] + timedelta(hours=1)
        if (start is None or start <= settlement) and (
          end is None or settlement <= end
        ):
          page.append(
            FundingRate(time=settlement, rate=Decimal(str(row['relativeFundingRate'])))
          )
      yield page

    return PaginatedResponse(pages())

  async def open_orders(self) -> Sequence[OrderState]:
    """Private Futures order reads are outside this public implementation."""
    raise NotImplementedError('Kraken Futures supports public market data only')

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Private Futures fills are outside this public implementation."""
    raise NotImplementedError('Kraken Futures supports public market data only')

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """Private Futures streams are outside this public implementation."""
    raise NotImplementedError('Kraken Futures supports public market data only')

  async def available_notional(self) -> Decimal:
    """Private Futures buying power is outside this public implementation."""
    raise NotImplementedError('Kraken Futures supports public market data only')

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """This adapter does not place Futures orders."""
    raise NotImplementedError('Kraken Futures supports public market data only')

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """This adapter does not cancel Futures orders."""
    raise NotImplementedError('Kraken Futures supports public market data only')

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    """Private funding payments are outside this public implementation."""
    raise NotImplementedError('Kraken Futures supports public market data only')

  async def perp_position(self) -> PerpPosition:
    """Private Futures positions are outside this public implementation."""
    raise NotImplementedError('Kraken Futures supports public market data only')

  async def perp_collateral(self) -> PerpCollateral:
    """Private Futures collateral is outside this public implementation."""
    raise NotImplementedError('Kraken Futures supports public market data only')
