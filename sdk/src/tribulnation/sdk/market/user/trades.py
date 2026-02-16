from typing_extensions import Sequence, AsyncIterable, Any
from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.core import SDK

class Trades(SDK):

  @dataclass(kw_only=True)
  class Trade:
    @dataclass(kw_only=True)
    class Fee:
      amount: Decimal
      """Fee paid (or received if negative, in fee asset units)."""
      asset: str

    id: str | None
    price: Decimal
    qty: Decimal
    """Signed quantity (netagive -> sell, positive -> buy)"""
    time: datetime
    maker: bool
    fee: Fee | None = None
    details: Any = None

  @SDK.method
  @abstractmethod
  def history(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[Trade]]:
    """Fetch your trades."""

  async def history_sync(self, start: datetime, end: datetime) -> Sequence[Trade]:
    """Fetch your trades without streaming."""
    out: list[Trades.Trade] = []
    async for page in self.history(start, end):
      out.extend(page)
    return out
		
  @SDK.method
  @abstractmethod
  def stream(self) -> AsyncIterable[Trade]:
    """Subscribe to your real-time trades."""