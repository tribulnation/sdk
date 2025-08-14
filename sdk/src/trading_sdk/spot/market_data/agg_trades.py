from abc import ABC, abstractmethod
from typing_extensions import Literal, AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

@dataclass
class AggTrade:
  price: Decimal
  qty: Decimal
  """Base asset quantity."""
  time: datetime
  """Time of the transaction."""
  maker: Literal['buyer', 'seller']
  """Which side was the maker."""

  
class AggTrades(ABC):
  @abstractmethod
  async def trades(
    self, base: str, quote: str, *,
    start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Sequence[AggTrade]]:
    """Fetch aggregate trades for the given symbol. Automatically paginates if needed.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `start`: if given, retrieves trades after this time.
    - `end`: if given, retrieves trades before this time.

    ### Ordering

    - If `start` is given, trades are ordered forwards by time.
    - Otherwise, ordered backwards by time.
    """
    ...
  