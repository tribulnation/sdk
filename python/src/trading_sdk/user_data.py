from typing_extensions import Protocol, TypedDict, Sequence, AsyncIterable
from decimal import Decimal
from datetime import datetime

class UserData(Protocol):

  class UserTrade(TypedDict):
    id: str
    price: Decimal
    quantity: Decimal
    time: datetime
    buyer: bool
    maker: bool

  async def user_trades(
    self, symbol: str, *, limit: int | None = None,
    start: datetime | None = None, end: datetime | None = None,
    start_id: str | None = None
  ) -> Sequence[UserTrade]:
    ...

  async def user_trades_paged(
    self, symbol: str, *, limit: int | None = None,
    start: datetime, end: datetime,
  ) -> AsyncIterable[Sequence[UserTrade]]:
    """Aggregate trades, sorted by increasing time (recent last). Paged to collect all trades in a time range."""
    last = start
    ids = set()
    while last < end:
      new_trades = await self.user_trades(symbol, limit=limit, start=last)
      new_trades = [t for t in new_trades if t['id'] not in ids]
      if not new_trades:
        break
      ids.update(t['id'] for t in new_trades)
      yield new_trades
      last = new_trades[-1]['time']