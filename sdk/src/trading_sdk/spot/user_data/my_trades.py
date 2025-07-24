from typing_extensions import Protocol, TypedDict, AsyncIterable, Sequence
from decimal import Decimal
from datetime import datetime
from trading_sdk.types import Side

class Trade(TypedDict):
  id: str
  price: Decimal
  quantity: Decimal
  time: datetime
  side: Side
  maker: bool

class MyTrades(Protocol):
  def my_trades(
    self, symbol: str, *, limit: int | None = None,
    start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Sequence[Trade]]:
    """Fetch trades (from your account) on a given symbol. Automatically paginates if needed.
    
    - `symbol`: The symbol being traded, e.g. `BTCUSDT`
    - `limit`: The maximum number of trades to fetch in a single request.
    - `start`: The start time to query. If given, only trades after this time will be returned.
    - `end`: The end time to query. If given, only trades before this time will be returned.

    ### Ordering

    - If `start` is given, trades are ordered forwards by time.
    - Otherwise, ordered backwards by time.
    """
    ...