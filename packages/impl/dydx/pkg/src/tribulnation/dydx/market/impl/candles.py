"""Historical trade candles for one perpetual market, from the indexer."""

from typing_extensions import AsyncIterable, Mapping, Sequence
from datetime import datetime, timedelta

from tribulnation.sdk.market import Candle, CandleInterval

from typed_dydx.indexer.schemas import Candle as CandleRow, CandleResolution

from .mixin import MarketMixin

CANDLES_PAGE = 1000
"""Candles per `get_candles` request; the indexer's own maximum for `limit`."""

RESOLUTIONS: Mapping[CandleInterval, CandleResolution] = {
  '1m': '1MIN',
  '5m': '5MINS',
  '15m': '15MINS',
  '1h': '1HOUR',
  '4h': '4HOURS',
  '1d': '1DAY',
}
"""The indexer's resolution name for each contract interval."""

CANDLE_INTERVALS = frozenset(RESOLUTIONS)
"""Every contract interval has an indexer resolution."""


def parse_candle(row: CandleRow) -> Candle:
  """Map one indexer candle onto a `Candle`.

  `baseTokenVolume` is the base volume and `usdVolume` the quote turnover, every
  dYdX market being quoted in USD.
  """
  return Candle(
    time=row['startedAt'],
    open=row['open'],
    high=row['high'],
    low=row['low'],
    close=row['close'],
    volume=row['baseTokenVolume'],
    quote_volume=row['usdVolume'],
    trades=row['trades'],
  )


async def candles(
  self: MarketMixin,
  interval: CandleInterval,
  start: datetime,
  end: datetime,
) -> AsyncIterable[Sequence[Candle]]:
  """Yield the indexer's native pages with exclusive upper-bound filtering."""
  if start == end:
    return
  paging = self.indexer.data.get_candles_paged(
    self.market,
    resolution=RESOLUTIONS[interval],
    from_iso=start,
    to_iso=end + timedelta(milliseconds=1),
    limit=CANDLES_PAGE,
  ).via(self.call_dydx)
  async for rows in paging:
    page = [parse_candle(r) for r in rows if start <= r['startedAt'] < end]
    if page:
      yield page
