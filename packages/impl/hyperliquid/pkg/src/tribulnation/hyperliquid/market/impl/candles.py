"""Trade candles shared by Hyperliquid spot and perpetual markets."""

from datetime import datetime, timedelta
from typing_extensions import AsyncIterator, Sequence

from tribulnation.sdk.market import Candle, CandleInterval

from .mixin import PerpMarketMixin, SpotMarketMixin

CANDLE_INTERVALS = frozenset[CandleInterval]({'1m', '5m', '15m', '1h', '4h', '1d'})
"""Contract intervals available through candle snapshots."""


async def candles(
  self: SpotMarketMixin | PerpMarketMixin,
  interval: CandleInterval,
  start: datetime,
  end: datetime,
) -> AsyncIterator[Sequence[Candle]]:
  """Yield native pages within the venue's retention and the requested bounds."""
  if start == end:
    return
  paging = self.client.info.candle_snapshot_paged(
    self.asset_name,
    interval=interval,
    start_time=start,
    end_time=end + timedelta(milliseconds=1),
  ).via(self.call_hyperliquid)
  async for rows in paging:
    page = [
      Candle(
        time=r['t'],
        open=r['o'],
        high=r['h'],
        low=r['l'],
        close=r['c'],
        volume=r['v'],
        trades=r['n'],
      )
      for r in rows
      if start <= r['t'] < end
    ]
    if page:
      yield page
