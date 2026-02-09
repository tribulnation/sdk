from typing_extensions import AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from tribulnation.sdk.market.market_data.candles import Candles as _Candles, Candle

from mexc.futures.market_data.candles import Interval
from mexc_sdk.core import MarketMixin, wrap_exceptions

intervals: dict[Interval, timedelta] = {
  'Min1': timedelta(minutes=1),
  'Min5': timedelta(minutes=5),
  'Min15': timedelta(minutes=15),
  'Min30': timedelta(minutes=30),
  'Min60': timedelta(minutes=60),
  'Hour4': timedelta(hours=4),
  'Day1': timedelta(days=1),
  'Week1': timedelta(weeks=1),
}

def parse_interval(dt: timedelta) -> Interval:
  interval, _ = min(intervals.items(), key=lambda i: abs(i[1] - dt))
  return interval

@dataclass
class Candles(MarketMixin, _Candles):
  @wrap_exceptions
  async def _candles_impl(
    self, *,
    interval: timedelta,
    start: datetime, end: datetime,
    limit: int | None = None,
  ) -> AsyncIterable[Sequence[Candle]]:
    int = parse_interval(interval)
    async for data in self.client.futures.candles_paged(self.instrument, interval=int, start=start, end=end):
      yield [Candle(
        time=datetime.fromtimestamp(data['time'][i]),
        open=Decimal(data['open'][i]),
        high=Decimal(data['high'][i]),
        low=Decimal(data['low'][i]),
        close=Decimal(data['close'][i]),
        volume=Decimal(data['vol'][i]),
      ) for i in range(len(data['close']))]
