from typing_extensions import Protocol, AsyncIterable, Sequence, Literal
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from tribulnation.sdk.market.types import Side
from tribulnation.sdk.core import ChunkedStream, SDK

@dataclass
class Trade:
  @dataclass
  class Fee:
    asset: str
    amount: Decimal

  id: str
  price: Decimal
  qty: Decimal
  time: datetime
  side: Side
  fee: Fee | None = None
  maker: bool | None = None

  @property
  def sign(self) -> Literal[-1, 1]:
    return -1 if self.side == 'SELL' else 1

  @property
  def signed_qty(self) -> Decimal:
    return self.qty * self.sign

class MyTrades(SDK, Protocol):
  def my_trades(
    self, start: datetime, end: datetime,
  ) -> ChunkedStream[Trade]:
    """Fetch your trades."""
    return ChunkedStream(self._my_trades_impl(start=start, end=end))
  
  def _my_trades_impl(
    self, start: datetime, end: datetime,
  ) -> AsyncIterable[Sequence[Trade]]:
    ...