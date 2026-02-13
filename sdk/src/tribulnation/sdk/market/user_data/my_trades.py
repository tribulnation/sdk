from typing_extensions import AsyncIterable, Sequence, Literal
from abc import abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from tribulnation.sdk.core import ChunkedStream, SDK
from tribulnation.sdk.market.types import Side

@dataclass
class Trade:
  @dataclass
  class Fee:
    asset: str
    amount: Decimal

  id: str
  price: Decimal
  qty: Decimal
  """Signed quantity (netagive -> sell, positive -> buy)"""
  time: datetime
  fee: Fee | None = None
  maker: bool | None = None

  @property
  def side(self) -> Side:
    return 'BUY' if self.qty >= 0 else 'SELL'

class MyTrades(SDK):
  @SDK.method
  def my_trades(
    self, start: datetime, end: datetime,
  ) -> ChunkedStream[Trade]:
    """Fetch your trades."""
    return ChunkedStream(self._my_trades_impl(start=start, end=end))
  
  @abstractmethod
  def _my_trades_impl(
    self, start: datetime, end: datetime,
  ) -> AsyncIterable[Sequence[Trade]]:
    ...