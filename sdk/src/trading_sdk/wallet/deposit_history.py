from typing_extensions import Protocol, TypedDict, NotRequired, AsyncIterable, Sequence
from decimal import Decimal
from datetime import datetime
from trading_sdk.types import Network

class Deposit(TypedDict):
  source_address: str
  source_memo: NotRequired[str | None]
  amount: Decimal
  asset: str
  network: Network

class DepositHistory(Protocol):
  async def deposit_history(
    self, *, start: datetime | None = None,
    end: datetime | None = None
  ) -> AsyncIterable[Sequence[Deposit]]:
    """Fetch your deposits.
    
    - `start`: if given, retrieves deposits after this time.
    - `end`: if given, retrieves deposits before this time.
    """
    ...