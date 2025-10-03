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
  quote_volume: Decimal | None = None

class Candles(Protocol):
  def candles(
    self, instrument: str, /, *,
    interval: timedelta,
    start: datetime,
    end: datetime,
    limit: int | None = None,
  ) -> AsyncIterable[Sequence[Candle]]:
    """Fetch candles for a given symbol.
    
    - `instrument`: The instrument to get the candles for.
    - `interval`: The interval of the candles (may be adjusted depending on the exchange)
    - `start`: The start time to query. If given, only candles after this time will be returned.
    - `end`: The end time to query. If given, only candles before this time will be returned.
    - `limit`: Candles to retrieve by request.
    """
    ...

  async def candles_sync(
    self, instrument: str, /, *,
    interval: timedelta,
    start: datetime,
    end: datetime,
    limit: int | None = None,
  ) -> Sequence[Candle]:
    """Fetch candles for a given symbol, without streaming.
    
    - `instrument`: The instrument to get the candles for.
    - `interval`: The interval of the candles (may be adjusted depending on the exchange)
    - `start`: The start time to query. If given, only candles after this time will be returned.
    - `end`: The end time to query. If given, only candles before this time will be returned.
    - `limit`: Candles to retrieve by request.
    """
    candles: list[Candle] = []
    async for chunk in self.candles(instrument, interval=interval, start=start, end=end, limit=limit):
      candles.extend(chunk)
    return candles

class SpotCandles(Candles, Protocol):
  def spot_candles(
    self, base: str, quote: str, /, *,
    interval: timedelta,
    start: datetime,
    end: datetime,
    limit: int | None = None,
  ) -> AsyncIterable[Sequence[Candle]]:
    """Fetch candles for a given spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `interval`: The interval of the candles (may be adjusted depending on the exchange)
    - `start`: The start time to query. If given, only candles after this time will be returned.
    - `end`: The end time to query. If given, only candles before this time will be returned.
    - `limit`: Candles to retrieve by request.
    """
    ...

  async def spot_candles_sync(
    self, base: str, quote: str, /, *,
    interval: timedelta,
    start: datetime,
    end: datetime,
    limit: int | None = None,
  ) -> Sequence[Candle]:
    """Fetch candles for a given spot instrument, without streaming."""
    candles: list[Candle] = []
    async for chunk in self.spot_candles(base, quote, interval=interval, start=start, end=end, limit=limit):
      candles.extend(chunk)
    return candles

class PerpCandles(Candles, Protocol):
  def perp_candles(
    self, base: str, quote: str, /, *,
    interval: timedelta,
    start: datetime,
    end: datetime,
    limit: int | None = None,
  ) -> AsyncIterable[Sequence[Candle]]:
    ...

  async def perp_candles_sync(
    self, base: str, quote: str, /, *,
    interval: timedelta,
    start: datetime,
    end: datetime,
    limit: int | None = None,
  ) -> Sequence[Candle]:
    candles: list[Candle] = []
    async for chunk in self.perp_candles(base, quote, interval=interval, start=start, end=end, limit=limit):
      candles.extend(chunk)
    return candles

class InversePerpCandles(Candles, Protocol):
  def inverse_perp_candles(
    self, currency: str, /, *,
    interval: timedelta,
    start: datetime,
    end: datetime,
    limit: int | None = None,
  ) -> AsyncIterable[Sequence[Candle]]:
    ...

  async def inverse_perp_candles_sync(
    self, currency: str, /, *,
    interval: timedelta,
    start: datetime,
    end: datetime,
    limit: int | None = None,
  ) -> Sequence[Candle]:
    candles: list[Candle] = []
    async for chunk in self.inverse_perp_candles(currency, interval=interval, start=start, end=end, limit=limit):
      candles.extend(chunk)
    return candles