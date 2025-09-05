from typing_extensions import Protocol
from trading_sdk.types import Num

class Redeem(Protocol):
  async def redeem(self, product: str, *, amount: Num) -> None:
    """Redeem from an earn product.
    
    - `product`: The product to redeem.
    - `amount`: The amount to redeem.
    """
    ...