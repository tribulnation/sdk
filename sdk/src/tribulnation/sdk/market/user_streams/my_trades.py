from typing_extensions import AsyncIterable
from abc import abstractmethod

from tribulnation.sdk import SDK
from tribulnation.sdk.market.user_data.my_trades import Trade

class MyTrades(SDK):
  @SDK.method
  @abstractmethod
  def my_trades_stream(self) -> AsyncIterable[Trade]:
    """Stream of your trades."""
    ...
