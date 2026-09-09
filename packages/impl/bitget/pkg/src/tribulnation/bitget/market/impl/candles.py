"""Historical trade candles for spot pairs and perpetual contracts.

Bitget serves candles from two endpoint families per product line: a recent one, kept
for roughly the last two months, and a history one reaching back years. Spot's history
endpoint has no paged walk in the typed client (it pages by `endTime` alone, 200 rows
at a time), so spot candles come from the recent endpoint's walk and reach only as far
as it does; futures history does have a walk and is used for every window.
"""

from typing_extensions import AsyncIterator, Mapping, Sequence
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.market import Candle, CandleInterval, candle_width, candle_windows
from typed_bitget.schemas import MixCandle, MixKlineInterval, SpotKlineInterval

from .mixin import MarketMixin
from .parse import PERP
from .util import MILLISECOND

SPOT_INTERVALS: Mapping[CandleInterval, SpotKlineInterval] = {
  '1m': '1min',
  '5m': '5min',
  '15m': '15min',
  '1h': '1h',
  '4h': '4h',
  '1d': '1day',
}
"""Bitget spot's name for each contract interval: minutes spelt out, days as `1day`."""

PERP_INTERVALS: Mapping[CandleInterval, MixKlineInterval] = {
  '1m': '1m',
  '5m': '5m',
  '15m': '15m',
  '1h': '1H',
  '4h': '4H',
  '1d': '1D',
}
"""Bitget futures' name for each contract interval: hours and days in capitals."""

CANDLE_INTERVALS = frozenset(SPOT_INTERVALS)
"""Every contract interval has a Bitget interval on both product lines."""

SPOT_PAGE = 1000
"""Rows per `classic.spot.candles` page; the cap the venue enforces (confirmed live)."""

PERP_PAGE = 200
"""Rows per `classic.mix.market.candles.history` page.

The client declares a range of 1 to 1000, but the venue refuses anything past 200
(`40053: limit should be between 1~200`, confirmed live), so the walk runs at the
venue's cap.
"""

SpotCandle = tuple[
  datetime, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal
]
"""One spot row: open time, open, high, low, close, base volume, USDT volume, quote volume."""


def parse_spot_candle(row: SpotCandle) -> Candle:
  """Map one spot candle row onto a `Candle`.

  The row carries the volume three ways; the base coin and the quote coin are the
  contract's own pairing, the USDT conversion between them is dropped.
  """
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


def parse_perp_candle(row: MixCandle) -> Candle:
  """Map one futures candle row onto a `Candle`."""
  time, open, high, low, close, volume, quote_volume = row
  return Candle(
    time=time,
    open=open,
    high=high,
    low=low,
    close=close,
    volume=volume,
    quote_volume=quote_volume,
  )


async def spot_candles(
  self: MarketMixin,
  interval: CandleInterval,
  start: datetime,
  end: datetime,
) -> AsyncIterator[Sequence[Candle]]:
  """Walk a spot pair's trade candles in native order within bounded windows.

  `classic.spot.candles` bounds `startTime` exclusively and `endTime` inclusively on
  open time, keeps the newest `limit` rows of a window, and the client's walk pages it
  newest-first. Sweep forward windows one candle short of a page, retaining each
  response's order and only opening timestamps in the half-open window. Expanding
  wire bounds by a millisecond preserves submillisecond caller bounds.

  The endpoint only keeps recent candles -- about two months of hourly ones, less at
  finer intervals (confirmed live) -- and answers nothing older, so a `start` past
  that horizon yields fewer candles than the window holds.
  """
  granularity = SPOT_INTERVALS[interval]

  def walk(lower: datetime, upper: datetime):
    """Walk one bounded window with request-level retry middleware."""
    return self.client.classic.spot.candles_paged(
      self.symbol,
      granularity=granularity,
      start_time=lower - MILLISECOND,
      end_time=upper + MILLISECOND,
      limit=SPOT_PAGE,
      validate=self.validate,
    ).via(self.call)

  for lower, upper in candle_windows(start, end, interval, size=SPOT_PAGE - 1):
    async for rows in walk(lower, upper):
      page = [parse_spot_candle(r) for r in rows if lower <= r[0] < upper]
      if page:
        yield page


async def perp_candles(
  self: MarketMixin,
  interval: CandleInterval,
  start: datetime,
  end: datetime,
) -> AsyncIterator[Sequence[Candle]]:
  """Walk a perpetual contract's candles in native order within bounded windows.

  `classic.mix.market.candles.history` reaches back to the contract's listing (2020
  for BTCUSDT, confirmed live). It answers the `(endTime - startTime) / width` newest
  candles that *close* by `endTime`. Send the upper bound one width and one
  millisecond later so an opening before a fractional end is retained, then filter
  opening timestamps to `[lower, upper)`. Windows leave two boundary slots under
  the page cap; neither rows nor pages are sorted or buffered across the history.
  """
  granularity = PERP_INTERVALS[interval]
  width = candle_width(interval)

  for lower, upper in candle_windows(start, end, interval, size=PERP_PAGE - 2):
    # Wire rounding can add two rows, filling the cap even though this window is
    # complete. A generic backwards pager would then request an end before start.
    rows = await self.call(
      lambda: self.client.classic.mix.market.candles.history(
        self.symbol,
        product_type=PERP,
        granularity=granularity,
        start_time=lower,
        end_time=upper + width + MILLISECOND,
        limit=PERP_PAGE,
        validate=self.validate,
      )
    )
    page = [parse_perp_candle(r) for r in rows if lower <= r[0] < upper]
    if page:
      yield page
