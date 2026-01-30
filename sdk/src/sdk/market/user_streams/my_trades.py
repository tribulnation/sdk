from typing_extensions import Protocol, AsyncIterable

from sdk.market.user_data.my_trades import Trade

class MyTrades(Protocol):
  def my_trades_stream(self) -> AsyncIterable[Trade]:
    """Stream of your trades."""
    ...
