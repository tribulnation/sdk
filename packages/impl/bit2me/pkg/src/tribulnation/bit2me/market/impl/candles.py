"""Bit2Me candle windows continue through empty intervals."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing_extensions import AsyncIterator, Literal, Mapping, Sequence

from tribulnation.sdk.market import Candle, CandleInterval, candle_width, candle_windows

from .mixin import MarketMixin

INTERVALS: Mapping[CandleInterval, Literal[1, 5, 15, 60, 240, 1440]] = {
  '1m': 1,
  '5m': 5,
  '15m': 15,
  '1h': 60,
  '4h': 240,
  '1d': 1440,
}
"""Venue interval widths in minutes."""

CANDLE_INTERVALS = frozenset(INTERVALS)
"""Contract intervals Bit2Me exposes."""


async def candles(
  self: MarketMixin,
  interval: CandleInterval,
  start: datetime,
  end: datetime,
) -> AsyncIterator[Sequence[Candle]]:
  """Read fixed windows because the limit counts slots, not returned rows.

  Some coarse intervals omit the start slot. Reserve a slot before each window
  and one for the end boundary, then filter without sorting or filling empty slots.
  """
  width = candle_width(interval)
  for lower, upper in candle_windows(start, end, interval, size=998):
    rows = await self.call_bit2me(
      lambda: self.client.v1.trading.candles(
        self.symbol,
        interval=INTERVALS[interval],
        start_time=lower - width,
        end_time=upper + timedelta(milliseconds=1),
        limit=1000,
      )
    )
    page = [
      Candle(
        time=r[0],
        open=Decimal(str(r[1])),
        high=Decimal(str(r[2])),
        low=Decimal(str(r[3])),
        close=Decimal(str(r[4])),
        volume=Decimal(str(r[5])),
      )
      for r in rows
      if lower <= r[0] < upper
    ]
    if page:
      yield page
