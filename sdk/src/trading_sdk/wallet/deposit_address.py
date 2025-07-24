from typing_extensions import Protocol, TypedDict, NotRequired

class Address(TypedDict):
  address: str
  memo: NotRequired[str | None]

class DepositAddress(Protocol):
  async def deposit_address(self, currency: str, *, network: str) -> Address:
    """Get the deposit address for a currency.
    
    - `currency`: The currency to get the deposit address for.
    - `network`: The network to get the deposit address for.
    """
    ...