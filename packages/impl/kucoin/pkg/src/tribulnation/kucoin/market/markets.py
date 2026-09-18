"""Read-only spot and linear perpetual Market objects."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing_extensions import AsyncContextManager, AsyncIterable, Never, Sequence

from tribulnation.sdk.core import OverflowPolicy, PaginatedResponse
from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  Collateral,
  FundingPayment,
  FundingRate,
  Market,
  NextFunding,
  Order,
  OrderResponse,
  OrderState,
  PerpCollateral,
  PerpMarket,
  PerpPosition,
  Position,
  Rules,
  Settings,
  Trade,
)
from . import books
from .candles import CANDLE_INTERVALS, perp_candles, spot_candles
from .common import Public


@dataclass(frozen=True, kw_only=True)
class SpotMarket(Public, Market):
  """Classic spot public data; private Market methods are deliberately unsupported."""

  symbol: str
  CANDLE_INTERVALS = CANDLE_INTERVALS

  @property
  def market_id(self) -> str:
    """Keep the native KuCoin symbol."""
    return self.symbol

  @property
  def exchange_id(self) -> str:
    """Spot uses the Catalogue's explicit exchange ID."""
    return 'spot'

  @property
  def multiplier(self) -> Decimal:
    """Spot quantities already use base units."""
    return Decimal(1)

  async def depth(self, *, levels: int | None = None) -> Book:
    """Fetch up to 100 public price levels per side."""
    return await books.depth(
      self.shared, self.exchange_id, self.symbol, self.multiplier, levels=levels
    )

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """Subscribe to up to five levels with bounded per-subscriber buffering."""
    return books.depth_stream(
      self.shared,
      self.exchange_id,
      self.symbol,
      self.multiplier,
      levels=levels,
      queue_size=queue_size,
      overflow=overflow,
    )

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Return spot constraints without fetching account fees."""
    row = (await self.shared.spot_symbols(refetch=refetch))[self.symbol]
    return Rules(
      fee_asset=row['feeCurrency'],
      tick_size=row['priceIncrement'],
      step_size=row['baseIncrement'],
      fixed_min_qty=row['baseMinSize'],
      max_qty=row['baseMaxSize'],
      min_value=row['minFunds'],
      api=row['enableTrading'],
      details=row,
    )

  def candles(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> PaginatedResponse[Candle]:
    """Read native spot candles in required aware, half-open bounds."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(
      spot_candles(self.shared, self.symbol, interval, start, end)
    )

  async def query_order(self, id: str) -> OrderState | None:
    """Order queries are outside the public Market surface."""
    raise NotImplementedError('KuCoin Market supports public data only')

  async def open_orders(self) -> Sequence[OrderState]:
    """Open orders are outside the public Market surface."""
    raise NotImplementedError('KuCoin Market supports public data only')

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Own fills remain on the separate Report surface."""
    raise NotImplementedError(
      'KuCoin Market supports public data only; use Report for spot fills'
    )

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """Private fill streams are outside the public Market surface."""
    raise NotImplementedError('KuCoin Market supports public data only')

  async def position(self) -> Position:
    """Private positions are outside the public Market surface."""
    raise NotImplementedError('KuCoin Market supports public data only')

  async def collateral(self) -> Collateral:
    """Private collateral is outside the public Market surface."""
    raise NotImplementedError('KuCoin Market supports public data only')

  async def available_notional(self) -> Decimal:
    """Account buying power is outside the public Market surface."""
    raise NotImplementedError('KuCoin Market supports public data only')

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """This adapter does not place orders."""
    raise NotImplementedError('KuCoin Market supports public data only')

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Never:
    """This adapter does not cancel orders."""
    raise NotImplementedError('KuCoin Market supports public data only')


@dataclass(frozen=True, kw_only=True)
class LinearPerpMarket(SpotMarket, PerpMarket):
  """Linear perpetual public data, normalized from lots to base units."""

  contract_multiplier: Decimal

  @property
  def exchange_id(self) -> str:
    """Linear perpetuals use the explicit perp product identity."""
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
    row = await self.shared.call(lambda: self.shared.client.futures.symbol(self.symbol))
    return Decimal(str(row['indexPrice']))

  async def next_funding(self) -> NextFunding:
    """Use the dedicated funding endpoint's rate, settlement time and interval."""
    row = await self.shared.call(
      lambda: self.shared.client.futures.funding_fees.current_funding_rate(self.symbol)
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
    lower = start if start is not None else datetime(1970, 1, 1, tzinfo=timezone.utc)
    upper = end if end is not None else datetime.now(timezone.utc)
    if lower.utcoffset() is None or upper.utcoffset() is None or upper < lower:
      raise ValueError('Funding bounds must be aware and end must not precede start')

    async def pages():
      """Retry each native page independently and filter inclusive SDK bounds."""
      source = self.shared.client.futures.funding_fees.public_funding_history_paged(
        self.symbol,
        from_=lower,
        to=upper,
      ).via(self.shared.call)
      async for page in source:
        yield [
          FundingRate(time=r['timepoint'], rate=Decimal(str(r['fundingRate'])))
          for r in page
          if lower <= r['timepoint'] <= upper
        ]

    return PaginatedResponse(pages())

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    """Account funding payments are outside the public Market surface."""
    raise NotImplementedError('KuCoin Market supports public data only')

  async def perp_position(self) -> PerpPosition:
    """Private futures positions are outside the public Market surface."""
    raise NotImplementedError('KuCoin Market supports public data only')

  async def perp_collateral(self) -> PerpCollateral:
    """Private futures collateral is outside the public Market surface."""
    raise NotImplementedError('KuCoin Market supports public data only')
