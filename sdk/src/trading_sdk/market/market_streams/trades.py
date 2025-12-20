from typing_extensions import Protocol, AsyncIterable

from trading_sdk.market.market_data.trades import Trade

class Trades(Protocol):
  def trades_stream(self) -> AsyncIterable[Trade]:
    """Stream of market trades."""
    ...
    