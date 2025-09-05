from typing_extensions import Protocol, Literal
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from trading_sdk.types import Side

OrderStatus = Literal['NEW', 'PARTIALLY_FILLED', 'FILLED', 'CANCELED', 'PARTIALLY_CANCELED', 'UNTRIGGERED']

@dataclass
class OrderState:
  id: str
  price: Decimal
  qty: Decimal
  filled_qty: Decimal
  side: Side
  status: OrderStatus
  time: datetime

  @property
  def quote_qty(self) -> Decimal:
    return self.qty * self.price

  @property
  def unfilled_qty(self) -> Decimal:
    return self.qty - self.filled_qty
  
class QueryOrder(Protocol):
  async def query_order(self, base: str, quote: str, *, id: str) -> OrderState:
    """Query an order.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `id`: The ID of the order to query.
    """
    ...