from typing_extensions import Protocol, AsyncIterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from trading_sdk.market.types import Instrument, Side

@dataclass
class Trade:
  @dataclass
  class Fee:
    asset: str
    amount: Decimal

  id: str
  price: Decimal
  qty: Decimal
  time: datetime
  side: Side
  fee: Fee | None = None
  maker: bool | None = None

class MyTrades(Protocol):
  def my_trades(
    self, instrument: Instrument, *,
    start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Sequence[Trade]]:
    """Fetch trades (from your account) on a given symbol. Automatically paginates if needed.
    
    - `instrument`: The instrument to get the trades for.
    - `start`: The start time to query. If given, only trades after this time will be returned.
    - `end`: The end time to query. If given, only trades before this time will be returned.
    """
    ...

  async def my_trades_any(self, instrument: str, *, start: datetime | None = None, end: datetime | None = None) -> AsyncIterable[Sequence[Trade]]:
    """Fetch trades (from your account) on a given instrument by the exchange-specific name.
    
    - `instrument`: The name of the instrument to get the trades for.
    - `start`: The start time to query. If given, only trades after this time will be returned.
    - `end`: The end time to query. If given, only trades before this time will be returned.
    """
    async for batch in self.my_trades({'type': 'any', 'name': instrument}, start=start, end=end):
      yield batch

  async def my_trades_spot(self, base: str, quote: str, *, start: datetime | None = None, end: datetime | None = None) -> AsyncIterable[Sequence[Trade]]:
    """Fetch trades (from your account) on a given spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `start`: The start time to query. If given, only trades after this time will be returned.
    - `end`: The end time to query. If given, only trades before this time will be returned.
    """
    async for batch in self.my_trades({'type': 'spot', 'base': base, 'quote': quote}, start=start, end=end):
      yield batch

  async def my_trades_perp(self, base: str, quote: str, *, start: datetime | None = None, end: datetime | None = None) -> AsyncIterable[Sequence[Trade]]:
    """Fetch trades (from your account) on a given perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `start`: The start time to query. If given, only trades after this time will be returned.
    - `end`: The end time to query. If given, only trades before this time will be returned.
    """
    async for batch in self.my_trades({'type': 'perp', 'base': base, 'quote': quote}, start=start, end=end):
      yield batch

  async def my_trades_sync(
    self, instrument: Instrument, *,
    start: datetime | None = None, end: datetime | None = None
  ) -> Sequence[Trade]:
    """Fetch trades (from your account) on a given symbol. Automatically paginates if needed.
    
    - `instrument`: The instrument to get the trades for.
    - `start`: The start time to query. If given, only trades after this time will be returned.
    - `end`: The end time to query. If given, only trades before this time will be returned.
    """
    trades: list[Trade] = []
    async for batch in self.my_trades(instrument, start=start, end=end):
      trades.extend(batch)
    return trades

  async def my_trades_any_sync(self, instrument: str, *, start: datetime | None = None, end: datetime | None = None) -> Sequence[Trade]:
    """Fetch trades (from your account) on a given instrument by the exchange-specific name, without streaming.
    
    - `instrument`: The name of the instrument to get the trades for.
    - `start`: The start time to query. If given, only trades after this time will be returned.
    - `end`: The end time to query. If given, only trades before this time will be returned.
    """
    return await self.my_trades_any_sync(instrument, start=start, end=end)

  async def my_trades_spot_sync(self, base: str, quote: str, *, start: datetime | None = None, end: datetime | None = None) -> Sequence[Trade]:
    """Fetch trades (from your account) on a given spot instrument, without streaming.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `start`: The start time to query. If given, only trades after this time will be returned.
    - `end`: The end time to query. If given, only trades before this time will be returned.
    """
    return await self.my_trades_spot_sync(base, quote, start=start, end=end)

  async def my_trades_perp_sync(self, base: str, quote: str, *, start: datetime | None = None, end: datetime | None = None) -> Sequence[Trade]:
    """Fetch trades (from your account) on a given perpetual instrument, without streaming.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `start`: The start time to query. If given, only trades after this time will be returned.
    - `end`: The end time to query. If given, only trades before this time will be returned.
    """
    return await self.my_trades_perp_sync(base, quote, start=start, end=end)