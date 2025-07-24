from typing_extensions import Protocol, TypedDict, NotRequired, TypeVar, Mapping
from decimal import Decimal

S = TypeVar('S', bound=str)

class Info(TypedDict):
  base_asset: str
  """Code of the base asset."""
  quote_asset: str
  """Code of the quote asset."""
  tick_size: Decimal
  """Tick size of the price (in quote units)."""
  step_size: Decimal
  """Step size of the quantity (in base units)."""
  min_quantity: NotRequired[Decimal]
  """Minimum quantity of the order (in base units)."""
  max_quantity: NotRequired[Decimal]
  """Maximum quantity of the order (in base units)."""
  min_price: NotRequired[Decimal]
  """Minimum price of the order (in quote units)."""
  max_price: NotRequired[Decimal]
  """Maximum price of the order (in quote units)."""

class ExchangeInfo(Protocol):
  async def exchange_info(self, *symbols: S) -> Mapping[S, Info]:
    """Get the exchange info for the given symbols."""
    ...