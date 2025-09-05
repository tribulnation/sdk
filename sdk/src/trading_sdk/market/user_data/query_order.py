from typing_extensions import Protocol, Literal
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from trading_sdk.market.types import Instrument, Side

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
  async def query_order(self, instrument: Instrument, *, id: str) -> OrderState:
    """Query an order.
    
    - `instrument`: The instrument to query the order for.
    - `id`: The ID of the order to query.
    """
    ...

  async def query_order_any(self, instrument: str, *, id: str) -> OrderState:
    """Query an order by the exchange-specific name.
    
    - `instrument`: The name of the instrument to query the order for.
    - `id`: The ID of the order to query.
    """
    return await self.query_order({'type': 'any', 'name': instrument}, id=id)
  
  async def query_order_spot(self, base: str, quote: str, *, id: str) -> OrderState:
    """Query a spot order.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `id`: The ID of the order to query.
    """
    return await self.query_order({'type': 'spot', 'base': base, 'quote': quote}, id=id)
  
  async def query_order_perp(self, base: str, quote: str, *, id: str) -> OrderState:
    """Query a perpetual order.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `id`: The ID of the order to query.
    """
    return await self.query_order({'type': 'perp', 'base': base, 'quote': quote}, id=id)