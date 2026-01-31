from typing_extensions import AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sdk.market.market_data.candles import Candles as _Candles, Candle

from mexc.core import timestamp as ts
from mexc.spot.market_data.candles import Interval
from mexc_sdk.core import MarketMixin, wrap_exceptions, spot_name

intervals: dict[Interval, timedelta] = {
  '1m': timedelta(minutes=1),
  '5m': timedelta(minutes=5), 
  '15m': timedelta(minutes=15),
  '30m': timedelta(minutes=30),
  '60m': timedelta(minutes=60),
  '4h': timedelta(hours=4),
  '1d': timedelta(days=1),
  '1W': timedelta(weeks=1),
  '1M': timedelta(days=30),
}

def parse_interval(dt: timedelta) -> Interval:
  interval, _ = min(intervals.items(), key=lambda i: abs(i[1] - dt))
  return interval

@dataclass
class Candles(_Candles, MarketMixin):
  @wrap_exceptions
  async def candles(
    self, *,
    interval: timedelta,
    start: datetime, end: datetime,
    limit: int | None = None,
  ) -> AsyncIterable[Sequence[Candle]]:
    int = parse_interval(interval)
    async for candles in self.client.spot.candles_paged(self.instrument, interval=int, start=start, end=end, limit=limit):
      yield [Candle(
        time=ts.parse(c.open_time),
        open=Decimal(c.open),
        high=Decimal(c.high),
        low=Decimal(c.low),
        close=Decimal(c.close),
        volume=Decimal(c.volume),
      ) for c in candles]
      