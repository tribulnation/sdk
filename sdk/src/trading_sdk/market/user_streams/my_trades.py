from typing_extensions import Protocol, AsyncIterable, Sequence

from trading_sdk.market.types import Instrument
from trading_sdk.market.user_data.my_trades import Trade

class MyTrades(Protocol):
  def my_trades(self, instrument: Instrument) -> AsyncIterable[Trade]:
    """Stream of your trades for the given symbol.
    
    - `instrument`: The instrument to get the trades for.
    """
    ...

  async def my_trades_any(self, instrument: str) -> AsyncIterable[Trade]:
    """Stream of your trades for the given instrument by the exchange-specific name.
    
    - `instrument`: The name of the instrument to get the trades for.
    """
    async for trade in self.my_trades({'type': 'any', 'name': instrument}):
      yield trade

  async def my_trades_spot(self, base: str, quote: str) -> AsyncIterable[Trade]:
    """Stream of your trades for the given spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    """
    async for trade in self.my_trades({'type': 'spot', 'base': base, 'quote': quote}):
      yield trade

  async def my_trades_perp(self, base: str, quote: str) -> AsyncIterable[Trade]:
    """Stream of your trades for the given perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    """
    async for trade in self.my_trades({'type': 'perp', 'base': base, 'quote': quote}):
      yield trade

  async def my_trades_sync(self, instrument: Instrument) -> Sequence[Trade]:
    """Stream of your trades for the given instrument, without streaming.
    
    - `instrument`: The instrument to get the trades for.
    """
    trades: list[Trade] = []
    async for trade in self.my_trades(instrument):
      trades.append(trade)
    return trades

  async def my_trades_any_sync(self, instrument: str) -> Sequence[Trade]:
    """Stream of your trades for the given instrument by the exchange-specific name, without streaming.
    
    - `instrument`: The name of the instrument to get the trades for.
    """
    return await self.my_trades_any_sync(instrument)
    
  async def my_trades_spot_sync(self, base: str, quote: str) -> Sequence[Trade]:
    """Stream of your trades for the given spot instrument, without streaming.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    """
    return await self.my_trades_spot_sync(base, quote)
    