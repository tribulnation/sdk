"""Historical trade candles for one spot symbol."""

from typing_extensions import AsyncIterable, Literal, Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from tribulnation.sdk.market import Candle, CandleInterval

from tribulnation.mexc.core.exc import wrap_exceptions
from .mixin import MarketMixin

CANDLES_PAGE = 500
"""Rows per `klines` page.

MEXC documents a 1000-row maximum but serves 500 whatever `limit` says (verified live
with `limit` 600 and 1000), and the client's walk stops on the first page shorter than
the `limit` it sent, so asking for more would silently end the sweep after one page.
"""

MILLISECOND = timedelta(milliseconds=1)
"""MEXC timestamps are epoch milliseconds, so this is one indivisible step."""

MexcInterval = Literal['1m', '5m', '15m', '30m', '60m', '4h', '1d', '1W', '1M']

MEXC_INTERVALS: Mapping[CandleInterval, MexcInterval] = {
  '1m': '1m',
  '5m': '5m',
  '15m': '15m',
  '1h': '60m',
  '4h': '4h',
  '1d': '1d',
}
"""MEXC's name for each contract interval; only the hour is spelt differently."""

CANDLE_INTERVALS = frozenset(MEXC_INTERVALS)
"""Every contract interval has a MEXC kline interval."""

KlineRow = tuple[
  datetime, Decimal, Decimal, Decimal, Decimal, Decimal, datetime, Decimal
]
"""One `klines` row: open time, open, high, low, close, volume, close time, quote volume."""


def parse_candle(row: KlineRow) -> Candle:
  """Map one kline row onto a `Candle`."""
  time, open, high, low, close, volume, _, quote_volume = row
  return Candle(
    time=time,
    open=open,
    high=high,
    low=low,
    close=close,
    volume=volume,
    quote_volume=quote_volume,
  )


@wrap_exceptions
async def candles(
  self: MarketMixin,
  interval: CandleInterval,
  start: datetime,
  end: datetime,
) -> AsyncIterable[Sequence[Candle]]:
  """Yield native pages, filtering to `[start, end)` after millisecond wire rounding."""
  if start == end:
    return
  paging = self.client.spot.http.market.candles_paged(
    self.instrument,
    interval=MEXC_INTERVALS[interval],
    start_time=start,
    end_time=end + MILLISECOND,
    limit=CANDLES_PAGE,
    validate=self.shared.validate,
  )
  async for rows in paging.via(self.call_mexc):
    page = [parse_candle(r) for r in rows if start <= r[0] < end]
    if page:
      yield page
