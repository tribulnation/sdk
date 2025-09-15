from typing_extensions import Protocol, AsyncIterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from trading_sdk.market.types import Side

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
    self, instrument: str, /, *,
    start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Sequence[Trade]]:
    """Fetch trades (from your account) on a given symbol. Automatically paginates if needed.
    
    - `instrument`: The instrument to get the trades for.
    - `start`: The start time to query. If given, only trades after this time will be returned.
    - `end`: The end time to query. If given, only trades before this time will be returned.
    """
    ...

  async def my_trades_sync(
    self, instrument: str, /, *,
    start: datetime | None = None, end: datetime | None = None
  ) -> Sequence[Trade]:
    """Fetch trades (from your account) on a given symbol, without streaming.
    
    - `instrument`: The instrument to get the trades for.
    - `start`: The start time to query. If given, only trades after this time will be returned.
    - `end`: The end time to query. If given, only trades before this time will be returned.
    """
    trades: list[Trade] = []
    async for batch in self.my_trades(instrument, start=start, end=end):
      trades.extend(batch)
    return trades


class SpotMyTrades(MyTrades, Protocol):
  def spot_my_trades(
    self, base: str, quote: str, /, *,
    start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Sequence[Trade]]:
    """Fetch trades (from your account) on a given spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `start`: The start time to query. If given, only trades after this time will be returned.
    - `end`: The end time to query. If given, only trades before this time will be returned.
    """
    ...

  async def spot_my_trades_sync(
    self, base: str, quote: str, /, *,
    start: datetime | None = None, end: datetime | None = None
  ) -> Sequence[Trade]:
    """Fetch trades (from your account) on a given spot instrument, without streaming.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `start`: The start time to query. If given, only trades after this time will be returned.
    - `end`: The end time to query. If given, only trades before this time will be returned.
    """
    trades: list[Trade] = []
    async for batch in self.spot_my_trades(base, quote, start=start, end=end):
      trades.extend(batch)
    return trades

class PerpMyTrades(MyTrades, Protocol):
  def perp_my_trades(
    self, base: str, quote: str, /, *,
    start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Sequence[Trade]]:
    """Fetch trades (from your account) on a given perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `start`: The start time to query. If given, only trades after this time will be returned.
    - `end`: The end time to query. If given, only trades before this time will be returned.
    """
    ...

  async def perp_my_trades_sync(
    self, base: str, quote: str, /, *,
    start: datetime | None = None, end: datetime | None = None
  ) -> Sequence[Trade]:
    """Fetch trades (from your account) on a given perpetual instrument, without streaming.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `start`: The start time to query. If given, only trades after this time will be returned.
    - `end`: The end time to query. If given, only trades before this time will be returned.
    """
    trades: list[Trade] = []
    async for batch in self.perp_my_trades(base, quote, start=start, end=end):
      trades.extend(batch)
    return trades

class InversePerpMyTrades(MyTrades, Protocol):
  def inverse_perp_my_trades(
    self, currency: str, /, *,
    start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Sequence[Trade]]:
    """Fetch trades (from your account) on a given inverse perpetual instrument.
    
    - `currency`: The currency, e.g. `BTC`.
    - `start`: The start time to query. If given, only trades after this time will be returned.
    - `end`: The end time to query. If given, only trades before this time will be returned.
    """
    ...

  async def inverse_perp_my_trades_sync(
    self, currency: str, /, *,
    start: datetime | None = None, end: datetime | None = None
  ) -> Sequence[Trade]:
    """Fetch trades (from your account) on a given inverse perpetual instrument, without streaming.

    - `currency`: The currency, e.g. `BTC`.
    - `start`: The start time to query. If given, only trades after this time will be returned.
    - `end`: The end time to query. If given, only trades before this time will be returned.
    """
    trades: list[Trade] = []
    async for batch in self.inverse_perp_my_trades(currency, start=start, end=end):
      trades.extend(batch)
    return trades