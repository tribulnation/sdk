"""Time helpers shared across the Binance surfaces."""

from typing_extensions import Iterator
from datetime import datetime, timedelta


def windows(
  start: datetime, end: datetime, size: timedelta
) -> Iterator[tuple[datetime, datetime]]:
  """Split `[start, end]` into consecutive windows of at most `size`.

  Binance caps most history endpoints per call (24h for spot fills, 7 days for USD-M
  fills, 90 days for deposits and withdrawals), so a wider request has to be swept.
  """
  cursor = start
  while cursor < end:
    stop = min(cursor + size, end)
    yield cursor, stop
    cursor = stop + timedelta(milliseconds=1)
