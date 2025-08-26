from abc import ABC, abstractmethod
from typing_extensions import AsyncIterable
from trading_sdk.spot.user_data.my_trades import Trade

class MyTrades(ABC):
  @abstractmethod
  def my_trades(self, base: str, quote: str) -> AsyncIterable[Trade]:
    """Stream of your trades for the given symbol.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    """
    ...