"""Historical trade candles for one perpetual market, from the indexer."""

from typing_extensions import AsyncIterable, Mapping, Sequence
from datetime import datetime, timedelta, timezone

from tribulnation.sdk.market import Candle, CandleInterval, candle_windows

from typed_dydx.indexer.schemas import Candle as CandleRow, CandleResolution

from .mixin import MarketMixin

CANDLES_PAGE = 1000
"""Candles per `get_candles` request; the indexer's own maximum for `limit`."""

MILLISECOND = timedelta(milliseconds=1)
"""The indexer takes ISO 8601 bounds with millisecond precision."""

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
  start: datetime | None,
  end: datetime | None,
) -> AsyncIterable[Sequence[Candle]]:
  """Walk this market's trade candles, oldest page first.

  The indexer answers newest-first and bounds `toISO` exclusively on open time, so
  the contract's inclusive `end` is passed one millisecond later. With a `start`, the
  range is swept in forward windows of one page each, every window read through the
  client's own walk (so a short response is confirmed rather than trusted), reversed,
  and trimmed to the contract's own bounds. Without one, the whole backwards walk is
  buffered before the first page is yielded: ascending order needs the earliest page
  first, and only the venue knows where that is. An open `end` is resolved to now.
  Every request goes through `call_dydx`, which translates the client's errors.
  """
  resolution = RESOLUTIONS[interval]
  if end is None:
    end = datetime.now(timezone.utc)

  def walk(lower: datetime | None, upper: datetime):
    """The client's newest-first walk over `[lower, upper]`, one request per page."""
    return self.indexer.data.get_candles_paged(
      self.market,
      resolution=resolution,
      from_iso=lower,
      to_iso=upper + MILLISECOND,
      limit=CANDLES_PAGE,
    ).via(self.call_dydx)

  if start is None:
    pages = [rows async for rows in walk(None, end)]
    for rows in reversed(pages):
      yield [parse_candle(r) for r in reversed(rows)]
    return
  # One candle short of the cap, so the client's walk sees a short page and never
  # spends a request confirming a window is exhausted.
  for lower, upper in candle_windows(start, end, interval, size=CANDLES_PAGE - 1):
    rows = [r for r in await walk(lower, upper) if lower <= r['startedAt'] <= upper]
    if rows:
      yield [parse_candle(r) for r in sorted(rows, key=lambda r: r['startedAt'])]
