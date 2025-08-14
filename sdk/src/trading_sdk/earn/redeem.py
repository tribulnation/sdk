from abc import ABC, abstractmethod
from trading_sdk.types import Num

class Redeem(ABC):
  @abstractmethod
  async def redeem(self, product: str, *, amount: Num):
    """Redeem from an earn product.
    
    - `product`: The product to redeem.
    - `amount`: The amount to redeem.
    """
    ...