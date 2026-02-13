from typing_extensions import AsyncIterable
from abc import abstractmethod

from tribulnation.sdk import SDK
from tribulnation.sdk.market.market_data.trades import Trade

class Trades(SDK):
  @SDK.method
  @abstractmethod
  def trades_stream(self) -> AsyncIterable[Trade]:
    """Stream of market trades."""
    ...
    