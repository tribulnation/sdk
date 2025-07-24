from typing_extensions import Protocol, TypedDict, Mapping, TypeVar

S = TypeVar('S', bound=str, default=str)

class Balance(TypedDict):
  free: str
  locked: str

class Balances(Protocol):
  async def balances(self, *currencies: S) -> Mapping[S, Balance]:
    """Get the `currencies` balances of your account."""
    ...