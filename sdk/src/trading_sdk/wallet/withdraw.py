from typing_extensions import Protocol
from trading_sdk.types import Num, Network

class Withdraw(Protocol):
  async def withdraw(
    self, asset: str, *, address: str, amount: Num,
    network: Network, memo: str | None = None,
    contract_address: str | None = None,
  ):
    """Withdraw funds.
    
    - `asset`: The asset to withdraw.
    - `address`: The address to withdraw to.
    - `amount`: The amount to withdraw.
    - `network`: The network to withdraw to.
    - `memo`: The memo to withdraw to (for some networks).
    - `contract_address`: The contract address to withdraw to. You can use it to make sure it's the token you expect.
    """
    ...