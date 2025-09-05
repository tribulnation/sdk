from typing_extensions import Protocol, Sequence, AsyncIterable
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timedelta

from trading_sdk.market.types import Instrument

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
    self, instrument: Instrument, *,
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

  async def candles_any(self, instrument: str, *, interval: timedelta, start: datetime, end: datetime, limit: int | None = None) -> AsyncIterable[Sequence[Candle]]:
    """Fetch candles for a given instrument by the exchange-specific name.
    
    - `instrument`: The name of the instrument to get the candles for.
    - `interval`: The interval of the candles (may be adjusted depending on the exchange)
    - `start`: The start time to query. If given, only candles after this time will be returned.
    - `end`: The end time to query. If given, only candles before this time will be returned.
    - `limit`: Candles to retrieve by request.
    """
    async for chunk in self.candles({'type': 'any', 'name': instrument}, interval=interval, start=start, end=end, limit=limit):
      yield chunk

  async def candles_spot(self, base: str, quote: str, *, interval: timedelta, start: datetime, end: datetime, limit: int | None = None) -> AsyncIterable[Sequence[Candle]]:
    """Fetch candles for a given spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `interval`: The interval of the candles (may be adjusted depending on the exchange)
    - `start`: The start time to query. If given, only candles after this time will be returned.
    - `end`: The end time to query. If given, only candles before this time will be returned.
    - `limit`: Candles to retrieve by request.
    """
    async for chunk in self.candles({'type': 'spot', 'base': base, 'quote': quote}, interval=interval, start=start, end=end, limit=limit):
      yield chunk

  async def candles_perp(self, base: str, quote: str, *, interval: timedelta, start: datetime, end: datetime, limit: int | None = None) -> AsyncIterable[Sequence[Candle]]:
    """Fetch candles for a given perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `interval`: The interval of the candles (may be adjusted depending on the exchange)
    - `start`: The start time to query. If given, only candles after this time will be returned.
    - `end`: The end time to query. If given, only candles before this time will be returned.
    - `limit`: Candles to retrieve by request.
    """
    async for chunk in self.candles({'type': 'perp', 'base': base, 'quote': quote}, interval=interval, start=start, end=end, limit=limit):
      yield chunk

  async def candles_sync(
    self, instrument: Instrument, *,
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
    candles = []
    async for chunk in self.candles(instrument, interval=interval, start=start, end=end, limit=limit):
      candles.extend(chunk)
    return candles

  async def candles_any_sync(self, instrument: str, *, interval: timedelta, start: datetime, end: datetime, limit: int | None = None) -> Sequence[Candle]:
    """Fetch candles for a given instrument by the exchange-specific name, without streaming.
    
    - `instrument`: The name of the instrument to get the candles for.
    - `interval`: The interval of the candles (may be adjusted depending on the exchange)
    - `start`: The start time to query. If given, only candles after this time will be returned.
    - `end`: The end time to query. If given, only candles before this time will be returned.
    - `limit`: Candles to retrieve by request.
    """
    return await self.candles_any_sync(instrument, interval=interval, start=start, end=end, limit=limit)
  
  async def candles_spot_sync(self, base: str, quote: str, *, interval: timedelta, start: datetime, end: datetime, limit: int | None = None) -> Sequence[Candle]:
    """Fetch candles for a given spot instrument, without streaming.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `interval`: The interval of the candles (may be adjusted depending on the exchange)
    - `start`: The start time to query. If given, only candles after this time will be returned.
    - `end`: The end time to query. If given, only candles before this time will be returned.
    - `limit`: Candles to retrieve by request.
    """
    return await self.candles_spot_sync(base, quote, interval=interval, start=start, end=end, limit=limit)

  async def candles_perp_sync(self, base: str, quote: str, *, interval: timedelta, start: datetime, end: datetime, limit: int | None = None) -> Sequence[Candle]:
    """Fetch candles for a given perpetual instrument, without streaming.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `interval`: The interval of the candles (may be adjusted depending on the exchange)
    - `start`: The start time to query. If given, only candles after this time will be returned.
    - `end`: The end time to query. If given, only candles before this time will be returned.
    - `limit`: Candles to retrieve by request.
    """
    return await self.candles_perp_sync(base, quote, interval=interval, start=start, end=end, limit=limit)
