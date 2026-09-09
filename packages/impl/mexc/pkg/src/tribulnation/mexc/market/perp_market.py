"""Read-only MEXC linear perpetual candles, books and public funding history."""

from collections.abc import AsyncIterable, AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing_extensions import AsyncContextManager, Literal

from typed_mexc.schemas import ContractSpec
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
from tribulnation.sdk.market.types.candles import candle_windows

from .impl import ExchangeMixin

MexcInterval = Literal['Min1', 'Min5', 'Min15', 'Min60', 'Hour4', 'Day1']
INTERVALS: Mapping[CandleInterval, MexcInterval] = {
  '1m': 'Min1',
  '5m': 'Min5',
  '15m': 'Min15',
  '1h': 'Min60',
  '4h': 'Hour4',
  '1d': 'Day1',
}
CANDLES_PAGE = 2000


def unsupported(method: str) -> NotImplementedError:
  """Name the deliberately unsupported perpetual surface without making a request."""
  return NotImplementedError(
    f'MEXC perpetual {method} is not implemented; public data only'
  )


@dataclass(frozen=True, kw_only=True)
class PerpMarket(ExchangeMixin, BasePerpMarket):
  """A linear contract; all quantities are converted from contracts to base units."""

  info: ContractSpec
  CANDLE_INTERVALS = frozenset(INTERVALS)

  @property
  def venue_id(self) -> str:
    """The venue identifier."""
    return 'mexc'

  @property
  def exchange_id(self) -> str:
    """The linear perpetual exchange identifier."""
    return 'perp'

  @property
  def market_id(self) -> str:
    """The exact native symbol."""
    return self.info['symbol']

  @property
  def contract_size(self) -> Decimal:
    """Base units in one linear contract."""
    return Decimal(str(self.info['contractSize']))

  async def depth(self, *, levels: int | None = None) -> Book:
    """Read a public snapshot and convert quantities to base units."""
    response = await self.call_mexc(
      lambda: self.client.futures.http.market.depth(
        self.market_id, limit=levels, validate=self.shared.validate
      )
    )
    data = response.get('data')
    if data is None:
      raise ValueError('MEXC depth response is missing data')
    return Book(
      bids=[
        Book.Entry(Decimal(str(p)), Decimal(str(q)) * self.contract_size)
        for p, q, _ in data['bids']
      ],
      asks=[
        Book.Entry(Decimal(str(p)), Decimal(str(q)) * self.contract_size)
        for p, q, _ in data['asks']
      ],
    )

  async def index(self, *, settings: Settings = {}) -> Decimal:
    """Read the venue's public index price."""
    response = await self.call_mexc(
      lambda: self.client.futures.http.market.index_price(
        self.market_id, validate=self.shared.validate
      )
    )
    data = response.get('data')
    if data is None:
      raise ValueError('MEXC index response is missing data')
    return Decimal(str(data['indexPrice']))

  async def next_funding(self) -> NextFunding:
    """Read the actual per-contract settlement time and cycle, never a fixed schedule."""
    response = await self.call_mexc(
      lambda: self.client.futures.http.market.funding_rate(
        self.market_id, validate=self.shared.validate
      )
    )
    data = response.get('data')
    if data is None:
      raise ValueError('MEXC funding state response is missing data')
    return NextFunding(
      rate=Decimal(str(data['fundingRate'])),
      time=data['nextSettleTime'],
      interval=timedelta(hours=data['collectCycle']),
    )

  @PaginatedResponse.lift
  async def funding_rates(
    self, start: datetime | None = None, end: datetime | None = None
  ):
    """Walk native history pages and retain inclusive bounds without assuming ordering."""
    for bound in (start, end):
      if bound is not None and bound.utcoffset() is None:
        raise ValueError('Funding bounds must be timezone-aware')
    if start is not None and end is not None and end < start:
      raise ValueError('Funding end must not precede start')
    page_num = 1
    seen: set[datetime] = set()
    while True:
      response = await self.call_mexc(
        lambda: self.client.futures.http.market.funding_rate_history(
          self.market_id,
          page_num=page_num,
          page_size=1000,
          validate=self.shared.validate,
        )
      )
      data = response.get('data')
      if data is None:
        raise ValueError('MEXC funding history response is missing data')
      rows = data['resultList']
      page: list[FundingRate] = []
      for row in rows:
        time = row['settleTime']
        if (
          time not in seen
          and (start is None or start <= time)
          and (end is None or time <= end)
        ):
          page.append(FundingRate(time=time, rate=Decimal(str(row['fundingRate']))))
          seen.add(time)
      if page:
        yield page
      if not rows or page_num >= data['totalPage']:
        return
      page_num += 1

  def candles(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> PaginatedResponse[Candle]:
    """Serve every contract interval with required aware, half-open bounds."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(self.walk_candles(interval, start, end))

  async def walk_candles(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> AsyncIterator[Sequence[Candle]]:
    """Segment capped requests, continue across empty windows and retain native order."""
    for lower, upper in candle_windows(start, end, interval, size=CANDLES_PAGE):
      response = await self.call_mexc(
        lambda: self.client.futures.http.market.candles(
          self.market_id,
          interval=INTERVALS[interval],
          start=lower,
          end=upper - timedelta(microseconds=1),
          validate=self.shared.validate,
        )
      )
      data = response.get('data')
      if data is None:
        raise ValueError('MEXC candles response is missing data')
      page: list[Candle] = []
      seen: set[datetime] = set()
      for time, open_, high, low, close, volume, amount in zip(
        data['time'],
        data['open'],
        data['high'],
        data['low'],
        data['close'],
        data['vol'],
        data['amount'],
        strict=True,
      ):
        if lower <= time < upper and time not in seen:
          page.append(
            Candle(
              time=time,
              open=Decimal(str(open_)),
              high=Decimal(str(high)),
              low=Decimal(str(low)),
              close=Decimal(str(close)),
              volume=Decimal(str(volume)) * self.contract_size,
              quote_volume=Decimal(str(amount)),
            )
          )
          seen.add(time)
      if page:
        yield page

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """Perpetual streams are not part of this public REST implementation."""
    raise unsupported('depth_stream')

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Account-specific perpetual rules/fees are not implemented."""
    raise unsupported('rules')

  async def open_orders(self) -> Sequence[OrderState]:
    """Private perpetual orders are not implemented."""
    raise unsupported('open_orders')

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Private perpetual fills are not implemented."""
    raise unsupported('trades_history')

  def trades_stream(
    self, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """Private perpetual streams are not implemented."""
    raise unsupported('trades_stream')

  async def available_notional(self) -> Decimal:
    """Private perpetual balances are not implemented."""
    raise unsupported('available_notional')

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Perpetual trading is deliberately not enabled."""
    raise unsupported('place_order')

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> object:
    """Perpetual trading is deliberately not enabled."""
    raise unsupported('cancel_order')

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    """Private perpetual settlements are not implemented on Market."""
    raise unsupported('funding_payments')

  async def perp_position(self) -> PerpPosition:
    """Private perpetual positions are not implemented on Market."""
    raise unsupported('perp_position')

  async def perp_collateral(self) -> PerpCollateral:
    """Private perpetual balances are not implemented on Market."""
    raise unsupported('perp_collateral')
