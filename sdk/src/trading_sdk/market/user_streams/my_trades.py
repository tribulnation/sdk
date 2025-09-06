from typing_extensions import Protocol, AsyncIterable

from trading_sdk.market.user_data.my_trades import Trade

class MyTrades(Protocol):
  def my_trades(self, instrument: str, /) -> AsyncIterable[Trade]:
    """Stream of your trades for the given symbol.
    
    - `instrument`: The instrument to get the trades for.
    """
    ...

class SpotMyTrades(MyTrades, Protocol):
  def spot_my_trades(self, base: str, quote: str, /) -> AsyncIterable[Trade]:
    """Stream of your trades for the given spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    """
    ...

class PerpMyTrades(MyTrades, Protocol):
  def perp_my_trades(self, base: str, quote: str, /) -> AsyncIterable[Trade]:
    """Stream of your trades for the given perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    """
    ...

class InversePerpMyTrades(MyTrades, Protocol):
  def inverse_perp_my_trades(self, currency: str, /) -> AsyncIterable[Trade]:
    """Stream of your trades for the given inverse perpetual instrument.
    
    - `currency`: The currency, e.g. `BTC`.
    """
    ...