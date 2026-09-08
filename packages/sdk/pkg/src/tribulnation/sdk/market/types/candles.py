"""Historical trade candles: the value type, the interval vocabulary, and the window
arithmetic implementations share when a venue answers newest-first or caps a request.
"""

from typing_extensions import Iterator, Literal, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

CandleInterval = Literal['1m', '5m', '15m', '1h', '4h', '1d']
"""Candle widths the contract covers. Venue extras (`1s`, `3d`, `1w`) are not exposed."""

CANDLE_WIDTHS: Mapping[CandleInterval, timedelta] = {
  '1m': timedelta(minutes=1),
  '5m': timedelta(minutes=5),
  '15m': timedelta(minutes=15),
  '1h': timedelta(hours=1),
  '4h': timedelta(hours=4),
  '1d': timedelta(days=1),
}
"""The wall-clock span one candle of each interval covers."""

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
"""Every venue here aligns its candle grid to the Unix epoch, in UTC."""


def candle_width(interval: CandleInterval) -> timedelta:
  """The wall-clock span one candle of `interval` covers."""
  return CANDLE_WIDTHS[interval]


@dataclass(kw_only=True)
class Candle:
  """One trade candle. Mark- and index-price candles are a different series."""

  time: datetime
  """Open time of the interval, timezone-aware. Never the close time: venues agree on
  open time and disagree on how they report closes."""
  open: Decimal
  high: Decimal
  low: Decimal
  close: Decimal
  volume: Decimal | None = None
  """Base-asset volume, or `None` where the venue reports none."""
  quote_volume: Decimal | None = None
  """Quote-asset turnover, or `None` where the venue only reports base volume."""
  trades: int | None = None
  """Trade count, where reported."""


def candle_windows(
  start: datetime, end: datetime, interval: CandleInterval, *, size: int
) -> Iterator[tuple[datetime, datetime]]:
  """Split `[start, end)` into adjacent windows holding at most `size` candle opens.

  A window `(lower, upper)` covers `lower <= time < upper`; the next starts at `upper`. The
  windows are aligned to the interval's own grid, so a `start` falling inside a candle
  never causes a candle to straddle two windows. Use windows when a venue refuses
  requests covering more than one page's worth of time.

  Args:
    start: Open time of the first candle wanted (inclusive).
    end: Exclusive upper bound on opening time.
    interval: Candle width, which fixes the grid the windows align to.
    size: Most candles one window may hold, typically the venue's page cap.
  """
  if size < 1:
    raise ValueError('Candle window size must be positive')
  if start.utcoffset() is None or end.utcoffset() is None:
    raise ValueError('Candle bounds must be timezone-aware')
  if end < start:
    raise ValueError('Candle end must not precede start')
  width = candle_width(interval)
  span = width * size
  start = start.astimezone(timezone.utc)
  end = end.astimezone(timezone.utc)
  grid = start - (start - EPOCH) % width
  lower = start
  page = 1
  while lower < end:
    yield lower, min(grid + span * page, end)
    lower = grid + span * page
    page += 1
