from abc import ABC, abstractmethod
from typing_extensions import AsyncIterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from trading_sdk.types import Side


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

class MyTrades(ABC):
  @abstractmethod
  def my_trades(
    self, base: str, quote: str, *,
    start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Sequence[Trade]]:
    """Fetch trades (from your account) on a given symbol. Automatically paginates if needed.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `start`: The start time to query. If given, only trades after this time will be returned.
    - `end`: The end time to query. If given, only trades before this time will be returned.

    ### Ordering

    - If `start` is given, trades are ordered forwards by time.
    - Otherwise, ordered backwards by time.
    """
    ...