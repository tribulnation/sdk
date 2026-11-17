"""Helpers for Bitget's wire quirks and window-capped history endpoints."""

from typing_extensions import Iterator
from datetime import datetime, timedelta

MILLISECOND = timedelta(milliseconds=1)
"""Bitget timestamps are epoch milliseconds, so this is one indivisible step."""

HISTORY_WINDOW = timedelta(days=90)
"""Widest window the fill history endpoints accept, in both account modes.

`classic.spot.order.fills`, `classic.mix.order.fills` and `uta.trade.order.fills` all
answer a wider one with `00001: startTime and endTime interval cannot be greater than
90 days` (confirmed live, 2026-09-08) instead of truncating it.
"""

PAGE = 100
"""Rows per page on the history and open-order endpoints; Bitget's documented maximum."""


def windows(
  start: datetime, end: datetime, span: timedelta
) -> Iterator[tuple[datetime, datetime]]:
  """Split `[start, end]` into consecutive sub-windows of at most `span`.

  Bitget caps how wide a single history query may be and rejects a wider one outright
  instead of truncating it, so a long sweep is walked one window at a time.
  """
  lower = start
  while lower <= end:
    upper = min(lower + span, end)
    yield lower, upper
    lower = upper + MILLISECOND
