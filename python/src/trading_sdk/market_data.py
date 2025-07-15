from typing_extensions import TypedDict, Sequence, AsyncIterable, Protocol, overload, Literal
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

  @overload
  async def order_book(self, symbol: str, *, limit: int | None = None, unsafe: Literal[True]) -> OrderBook: ...
  @overload
  async def order_book(self, symbol: str, *, limit: int | None = None, unsafe: bool = False) -> OrderBook | UnauthedError: ...
  
  class Trade(TypedDict):
    price: Decimal
    quantity: Decimal
    time: datetime
    buyer_maker: bool

  @overload
  async def trades(self, symbol: str, *, limit: int | None = None, unsafe: Literal[True]) -> Sequence[Trade]: ...
  @overload
  async def trades(self, symbol: str, *, limit: int | None = None, unsafe: bool = False) -> Sequence[Trade] | UnauthedError:
    """Recent trades, sorted by increasing time (recent last)."""
  
  @overload
  async def agg_trades(
    self, symbol: str, *,
    limit: int | None = None,
    start: datetime | None = None, start_id: str | None = None,
    end: datetime | None = None, unsafe: Literal[True]
  ) -> Sequence[Trade]: ...
  @overload
  async def agg_trades(
    self, symbol: str, *,
    limit: int | None = None,
    start: datetime | None = None, start_id: str | None = None,
    end: datetime | None = None, unsafe: bool = False
  ) -> Sequence[Trade] | UnauthedError:
    """Aggregate trades, sorted by increasing time (recent last)."""

  @overload
  def agg_trades_paged(
    self, symbol: str, *, limit: int | None = None,
    start: datetime, end: datetime, unsafe: Literal[True]
  ) -> AsyncIterable[Sequence[Trade]]:
    ...
  @overload
  def agg_trades_paged(
    self, symbol: str, *, limit: int | None = None,
    start: datetime, end: datetime, unsafe: bool = False
  ) -> AsyncIterable[Sequence[Trade] | UnauthedError]:
    ...
  async def agg_trades_paged(
    self, symbol: str, *, limit: int | None = None,
    start: datetime, end: datetime, unsafe: bool = False
  ) -> AsyncIterable[Sequence[Trade] | UnauthedError]:
    """Aggregate trades, sorted by increasing time (recent last). Paged to collect all trades in a time range."""
    last = start
    while last < end:
      new_trades = await self.agg_trades(symbol, limit=limit, start=last, end=last+timedelta(hours=1), unsafe=unsafe)
      if not new_trades:
        break
      yield new_trades
      if isinstance(new_trades, UnauthedError):
        break
      last = new_trades[-1]['time']
  