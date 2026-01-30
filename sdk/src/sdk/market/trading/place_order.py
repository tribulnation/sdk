from typing_extensions import Protocol, Sequence, Literal, overload
import asyncio

from sdk.market.types import Order, OrderState

ResponseModel = Literal['id', 'state']

class PlaceOrder(Protocol):
  @overload
  async def place_order(
    self, order: Order, *,
    response: Literal['id'] = 'id'
  ) -> str:
    """Place an order.
    
    - `order`: The order to place.

    Returns the order ID.
    """
    ...
  @overload
  async def place_order(
    self, order: Order, *,
    response: Literal['state']
  ) -> OrderState:
    """Place an order.
    
    - `order`: The order to place.

    Returns the order state.
    """
    ...
  async def place_order(
    self, order: Order, *,
    response: Literal['id', 'state'] = 'id'
  ) -> str | OrderState:
    ...

  @overload
  async def place_orders(
    self, orders: Sequence[Order], *,
    response: Literal['id'] = 'id'
  ) -> Sequence[str]:
    """Place multiple orders.
    
    - `orders`: The orders to place.

    Returns the order IDs.
    """
    ...
  @overload
  async def place_orders(
    self, orders: Sequence[Order], *,
    response: Literal['state']
  ) -> Sequence[OrderState]:
    """Place multiple orders.
    
    - `orders`: The orders to place.

    Returns the order states.
    """
    ...
  async def place_orders(
    self, orders: Sequence[Order], *,
    response: Literal['id', 'state'] = 'id'
  ) -> Sequence[str] | Sequence[OrderState]:
    return await asyncio.gather(*[self.place_order(order, response=response) for order in orders]) # type: ignore
