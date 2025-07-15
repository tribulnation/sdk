from typing_extensions import TypedDict, Sequence, AsyncIterable, Protocol
from datetime import datetime, timedelta
from decimal import Decimal

from trading_sdk.types import Num
from trading_sdk.errors import UnauthedError

class MarketData(Protocol):
  class BookEntry(TypedDict):
    amount: Decimal
    price: Decimal

  class OrderBook(TypedDict):
    asks: Sequence['MarketData.BookEntry']
    bids: Sequence['MarketData.BookEntry']

  async def order_book(self, symbol: str, *, limit: int | None = None) -> OrderBook | UnauthedError:
    ...
  
  class Trade(TypedDict):
    price: Decimal
    quantity: Decimal
    time: datetime
    buyer_maker: bool

  async def trades(self, symbol: str, *, limit: int | None = None) -> Sequence[Trade] | UnauthedError:
    """Recent trades, sorted by increasing time (recent last)."""
    ...
  
  async def agg_trades(
    self, symbol: str, *,
    limit: int | None = None,
    start: datetime | None = None, start_id: str | None = None,
    end: datetime | None = None,
  ) -> Sequence[Trade] | UnauthedError:
    """Aggregate trades, sorted by increasing time (recent last)."""
    ...

  async def agg_trades_paged(
    self, symbol: str, *,
    start: datetime, end: datetime,
  ) -> AsyncIterable[Sequence[Trade] | UnauthedError]:
    """Aggregate trades, sorted by increasing time (recent last). Paged to collect all trades in a time range."""
    last = start
    while last < end:
      new_trades = await self.agg_trades(symbol, limit=1000, start=last, end=last+timedelta(hours=1))
      if not new_trades:
        break
      yield new_trades
      if isinstance(new_trades, UnauthedError):
        break
      last = new_trades[-1]['time']
    