from typing_extensions import Protocol
from trading_sdk.types import Num

class Subscribe(Protocol):
  async def subscribe(self, product: str, *, amount: Num) -> None:
    """Subscribe to an earn product.
    
    - `product`: The product to subscribe to.
    - `amount`: The amount to subscribe to.
    """
    ...