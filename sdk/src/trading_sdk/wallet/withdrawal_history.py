from typing_extensions import Protocol, TypedDict, NotRequired, AsyncIterable, Sequence
from decimal import Decimal
from datetime import datetime
from trading_sdk.types import Network

class Withdrawal(TypedDict):
  address: str
  memo: NotRequired[str | None]
  amount: Decimal
  asset: str
  network: Network
  fee: Decimal

class WithdrawalHistory(Protocol):
  async def withdrawal_history(
    self, *, start: datetime | None = None,
    end: datetime | None = None
  ) -> AsyncIterable[Sequence[Withdrawal]]:
    """Fetch your withdrawals.
    
    - `start`: if given, retrieves withdrawals after this time.
    - `end`: if given, retrieves withdrawals before this time.
    """
    ...