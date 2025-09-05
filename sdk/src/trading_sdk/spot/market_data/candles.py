from typing_extensions import Protocol, Sequence, AsyncIterable
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timedelta

@dataclass
class Candle:
  open: Decimal
  high: Decimal
  low: Decimal
  close: Decimal
  volume: Decimal
  time: datetime

class Candles(Protocol):
  def candles(
    self, base: str, quote: str, *,
    interval: timedelta,
    start: datetime,
    end: datetime,
    limit: int | None = None,
  ) -> AsyncIterable[Sequence[Candle]]:
    """Fetch candles for a given symbol.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `interval`: The interval of the candles (may be adjusted depending on the exchange)
    - `start`: The start time to query. If given, only candles after this time will be returned.
    - `end`: The end time to query. If given, only candles before this time will be returned.
    - `limit`: Candles to retrieve by request.
    """
  
  async def candles_sync(
    self, base: str, quote: str, *,
    interval: timedelta,
    start: datetime,
    end: datetime,
    limit: int | None = None,
  ) -> Sequence[Candle]:
    """Fetch candles for a given symbol, without streaming.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `interval`: The interval of the candles (may be adjusted depending on the exchange)
    - `start`: The start time to query. If given, only candles after this time will be returned.
    - `end`: The end time to query. If given, only candles before this time will be returned.
    - `limit`: Candles to retrieve by request.
    """
    candles = []
    async for chunk in self.candles(base, quote, interval=interval, start=start, end=end, limit=limit):
      candles.extend(chunk)
    return candles