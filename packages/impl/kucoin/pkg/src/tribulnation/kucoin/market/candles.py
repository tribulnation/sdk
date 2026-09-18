"""Classic trade candles with bounded time windows and native volume units."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing_extensions import AsyncIterator, Literal

from tribulnation.sdk.market import Candle, CandleInterval
from tribulnation.sdk.market.types.candles import candle_windows
from .common import Shared

SpotInterval = Literal['1min', '5min', '15min', '1hour', '4hour', '1day']
PerpInterval = Literal[1, 5, 15, 60, 240, 1440]
SPOT_INTERVALS: dict[CandleInterval, SpotInterval] = {
  '1m': '1min',
  '5m': '5min',
  '15m': '15min',
  '1h': '1hour',
  '4h': '4hour',
  '1d': '1day',
}
PERP_INTERVALS: dict[CandleInterval, PerpInterval] = {
  '1m': 1,
  '5m': 5,
  '15m': 15,
  '1h': 60,
  '4h': 240,
  '1d': 1440,
}
CANDLE_INTERVALS = frozenset(SPOT_INTERVALS)


def inclusive_end(end: datetime, *, precision: timedelta) -> datetime:
  """Last representable wire timestamp strictly before an exclusive bound."""
  tick = end.replace(microsecond=0)
  if precision < timedelta(seconds=1):
    tick = end.replace(microsecond=end.microsecond // 1000 * 1000)
  return tick - precision if tick == end else tick


async def spot_candles(
  shared: Shared, symbol: str, interval: CandleInterval, start: datetime, end: datetime
) -> AsyncIterator[list[Candle]]:
  """Translate spot's time/open/close/high/low/base/quote rows."""
  for lower, upper in candle_windows(start, end, interval, size=1500):
    rows = await shared.call(
      lambda: shared.client.spot.klines(
        symbol,
        type=SPOT_INTERVALS[interval],
        start_at=lower,
        end_at=inclusive_end(upper, precision=timedelta(seconds=1)),
      )
    )
    yield [
      Candle(time=t, open=o, close=c, high=h, low=l, volume=v, quote_volume=q)
      for t, o, c, h, l, v, q in rows
      if lower <= t < upper
    ]


async def perp_candles(
  shared: Shared,
  symbol: str,
  multiplier: Decimal,
  interval: CandleInterval,
  start: datetime,
  end: datetime,
) -> AsyncIterator[list[Candle]]:
  """Use the live-observed 200-row cap; the Classic docs still claim 500."""
  for lower, upper in candle_windows(start, end, interval, size=200):
    rows = await shared.call(
      lambda: shared.client.futures.klines(
        symbol,
        granularity=PERP_INTERVALS[interval],
        from_=lower,
        to=inclusive_end(upper, precision=timedelta(milliseconds=1)),
      )
    )
    yield [
      Candle(
        time=t,
        open=Decimal(str(o)),
        high=Decimal(str(h)),
        low=Decimal(str(l)),
        close=Decimal(str(c)),
        volume=Decimal(str(v)) * multiplier,
        quote_volume=Decimal(str(q)),
      )
      for t, o, h, l, c, v, q in rows
      if lower <= t < upper
    ]
