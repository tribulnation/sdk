"""Kraken's retained OHLC window, without inventing an older-history pager."""

from datetime import datetime
from typing_extensions import AsyncIterator, Literal, Mapping, Sequence

from tribulnation.sdk.market import Candle, CandleInterval, candle_width
from .mixin import MarketMixin

INTERVALS: Mapping[CandleInterval, Literal[1, 5, 15, 60, 240, 1440]] = {
  '1m': 1,
  '5m': 5,
  '15m': 15,
  '1h': 60,
  '4h': 240,
  '1d': 1440,
}
CANDLE_INTERVALS = frozenset(INTERVALS)


async def candles(
  self: MarketMixin,
  interval: CandleInterval,
  start: datetime,
  end: datetime,
) -> AsyncIterator[Sequence[Candle]]:
  """Return matching opens from the latest 720 rows, in the venue's order.

  `since` is a polling cursor, not a means of retrieving older data. The final,
  still-forming candle is returned only when its open lies inside the caller's range.
  """
  if start == end:
    return
  response = await self.call_kraken(
    lambda: self.client.spot.market_data.ohlc(
      self.altname,
      interval=INTERVALS[interval],
      since=start - candle_width(interval),
    )
  )
  rows = response.get(self.meta['pair']['key'])
  if rows is None:
    raise ValueError('Kraken candle response omitted the requested pair')
  if isinstance(rows, int):
    raise ValueError('Kraken returned a cursor instead of candle rows for the pair')
  seen: set[datetime] = set()
  page: list[Candle] = []
  for time, opening, high, low, close, _, volume, count in rows:
    if start <= time < end and time not in seen:
      seen.add(time)
      page.append(
        Candle(
          time=time,
          open=opening,
          high=high,
          low=low,
          close=close,
          volume=volume,
          trades=count,
        )
      )
  if page:
    yield page
