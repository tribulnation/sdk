"""Bounded Futures Charts trade-candle requests with half-open SDK bounds."""

from datetime import datetime, timedelta, timezone
from typing_extensions import AsyncIterator

from tribulnation.sdk.market import Candle, CandleInterval
from tribulnation.sdk.market.types.candles import CANDLE_WIDTHS, candle_windows
from .mixin import Shared

CANDLE_INTERVALS = frozenset(CANDLE_WIDTHS)
PAGE_SIZE = 2000
"""Verified request size, not a claim about the venue's maximum accepted count."""


def inclusive_end(end: datetime) -> datetime:
  """Return the final wire second strictly before the exclusive SDK upper bound."""
  second = end.astimezone(timezone.utc).replace(microsecond=0)
  return second - timedelta(seconds=1) if second == end else second


async def candles(
  shared: Shared,
  symbol: str,
  interval: CandleInterval,
  start: datetime,
  end: datetime,
) -> AsyncIterator[list[Candle]]:
  """Continue through empty windows and retry each request independently.

  A window holds at most 2000 possible opens, including a rounded-down start.
  A truncated window fails explicitly rather than skipping undisclosed rows.
  """
  for lower, upper in candle_windows(start, end, interval, size=PAGE_SIZE):
    response = await shared.call_kraken(
      lambda: shared.client.charts.candles(
        'trade',
        symbol=symbol,
        resolution=interval,
        from_=lower.replace(microsecond=0),
        to=inclusive_end(upper),
        count=PAGE_SIZE,
      )
    )
    if response['more_candles']:
      raise ValueError(
        'Kraken truncated a bounded candle window; refusing incomplete history'
      )
    seen: set[datetime] = set()
    page: list[Candle] = []
    for row in response['candles']:
      time = row['time']
      if lower <= time < upper and time not in seen:
        seen.add(time)
        page.append(
          Candle(
            time=time,
            open=row['open'],
            high=row['high'],
            low=row['low'],
            close=row['close'],
            volume=row['volume'],
          )
        )
    yield page
