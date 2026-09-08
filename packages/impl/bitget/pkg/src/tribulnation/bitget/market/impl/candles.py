"""Historical trade candles for spot pairs and perpetual contracts.

Bitget serves candles from two endpoint families per product line: a recent one, kept
for roughly the last two months, and a history one reaching back years. Spot's history
endpoint has no paged walk in the typed client (it pages by `endTime` alone, 200 rows
at a time), so spot candles come from the recent endpoint's walk and reach only as far
as it does; futures history does have a walk and is used for every window.
"""

from typing_extensions import AsyncIterator, Mapping, Sequence
from datetime import datetime, timezone
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
  start: datetime | None,
  end: datetime | None,
) -> AsyncIterator[Sequence[Candle]]:
  """Walk a spot pair's trade candles, oldest page first.

  `classic.spot.candles` bounds `startTime` exclusively and `endTime` inclusively on
  open time, keeps the newest `limit` rows of a window, and the client's walk pages it
  newest-first. With a `start`, the range is swept in forward windows one candle short
  of a page, each read through the client's walk (so a short response is confirmed
  rather than trusted), then trimmed and sorted. Without one, the whole backwards walk
  is buffered before the first page is yielded. An open `end` is resolved to now.

  The endpoint only keeps recent candles -- about two months of hourly ones, less at
  finer intervals (confirmed live) -- and answers nothing older, so a `start` past
  that horizon yields fewer candles than the window holds.
  """
  granularity = SPOT_INTERVALS[interval]
  if end is None:
    end = datetime.now(timezone.utc)

  def walk(lower: datetime | None, upper: datetime):
    """The client's newest-first walk over `[lower, upper]`, one request per page."""
    return self.client.classic.spot.candles_paged(
      self.symbol,
      granularity=granularity,
      start_time=lower - MILLISECOND if lower is not None else None,
      end_time=upper,
      limit=SPOT_PAGE,
      validate=self.validate,
    ).via(self.call)

  if start is None:
    pages = [rows async for rows in walk(None, end)]
    for rows in reversed(pages):
      yield [parse_spot_candle(r) for r in reversed(rows)]
    return
  for lower, upper in candle_windows(start, end, interval, size=SPOT_PAGE - 1):
    rows = [r for r in await walk(lower, upper) if lower <= r[0] <= upper]
    if rows:
      yield [parse_spot_candle(r) for r in sorted(rows, key=lambda r: r[0])]


async def perp_candles(
  self: MarketMixin,
  interval: CandleInterval,
  start: datetime | None,
  end: datetime | None,
) -> AsyncIterator[Sequence[Candle]]:
  """Walk a perpetual contract's trade candles, oldest page first.

  `classic.mix.market.candles.history` reaches back to the contract's listing (2020
  for BTCUSDT, confirmed live). It answers the `(endTime - startTime) / width` newest
  candles that *close* by `endTime` -- so an aligned `[start, end]` omits the candle
  opening at `end`, and `end` is sent one width later to include it (confirmed live
  against every offset from a millisecond to a width). That makes a window of `n`
  candles an `n + 1` width span, so windows run two candles short of the page cap to
  keep every request one short page. Same sweep as the spot walk otherwise: forward
  windows with a `start`, the whole backwards walk buffered without one, an open
  `end` resolved to now.
  """
  granularity = PERP_INTERVALS[interval]
  width = candle_width(interval)
  if end is None:
    end = datetime.now(timezone.utc)

  def walk(lower: datetime | None, upper: datetime):
    """The client's newest-first walk over `[lower, upper]`, one request per page."""
    return self.client.classic.mix.market.candles.history_paged(
      self.symbol,
      product_type=PERP,
      granularity=granularity,
      start_time=lower,
      end_time=upper + width,
      limit=PERP_PAGE,
      validate=self.validate,
    ).via(self.call)

  if start is None:
    pages = [rows async for rows in walk(None, end)]
    for rows in reversed(pages):
      yield [parse_perp_candle(r) for r in reversed(rows)]
    return
  for lower, upper in candle_windows(start, end, interval, size=PERP_PAGE - 2):
    rows = [r for r in await walk(lower, upper) if lower <= r[0] <= upper]
    if rows:
      yield [parse_perp_candle(r) for r in sorted(rows, key=lambda r: r[0])]
