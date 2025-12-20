from typing_extensions import Protocol, Sequence, AsyncIterable
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timedelta

from trading_sdk.util import ChunkedStream

@dataclass
class Candle:
  open: Decimal
  high: Decimal
  low: Decimal
  close: Decimal
  volume: Decimal
  time: datetime
  quote_volume: Decimal | None = None

class Candles(Protocol):
  def candles(
    self, *,
    interval: timedelta,
    start: datetime,
    end: datetime,
    limit: int | None = None,
  ) -> ChunkedStream[Candle]:
    """Fetch market candles.
    
    - `interval`: The interval of the candles (may be adjusted depending on the exchange)
    - `start`: The start time to query. If given, only candles after this time will be returned.
    - `end`: The end time to query. If given, only candles before this time will be returned.
    - `limit`: Candles to retrieve by request.
    """
    return ChunkedStream(self._candles_impl(interval=interval, start=start, end=end, limit=limit))
  
  def _candles_impl(
    self, *,
    interval: timedelta,
    start: datetime,
    end: datetime,
    limit: int | None = None,
  ) -> AsyncIterable[Sequence[Candle]]:
    ...

