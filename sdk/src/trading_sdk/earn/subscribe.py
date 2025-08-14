from abc import ABC, abstractmethod
from trading_sdk.types import Num

class Subscribe(ABC):
  @abstractmethod
  async def subscribe(self, product: str, *, amount: Num):
    """Subscribe to an earn product.
    
    - `product`: The product to subscribe to.
    - `amount`: The amount to subscribe to.
    """
    ...