from typing_extensions import AsyncIterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from sdk.reporting import Transactions as _Transactions, Transaction

from bitget_sdk.core import SdkMixin
from .spot import SpotTransactions
from .futures import FutureTransactions
from .margin import MarginTransactions
from .internal_transfers import parse_internal_transfers

class AutoDetect:
  ...

AUTO_DETECT = AutoDetect()

@dataclass
class Transactions(SdkMixin, _Transactions):
  """Bitget Transactions
  
  **Does not support**:
  - P2P trading
  - Copy trading
  """
  unkwown_types_as_other: bool = field(kw_only=True, default=True)
  tz: timezone | AutoDetect = AUTO_DETECT
  """Timezone of the API times (defaults to the local timezone)."""

  @property
  def timezone(self) -> timezone:
    if isinstance(self.tz, AutoDetect):
      return datetime.now().astimezone().tzinfo # type: ignore
    else:
      return self.tz

  def add_tz(self, tx: Transaction) -> Transaction:
    return tx.replace_time(tx.event.time.replace(tzinfo=self.timezone))

  def __post_init__(self):
    self.spot_transactions = SpotTransactions(self.client, unkwown_types_as_other=self.unkwown_types_as_other)
    self.future_transactions = FutureTransactions(self.client, unkwown_types_as_other=self.unkwown_types_as_other)
    self.margin_transactions = MarginTransactions(self.client, unkwown_types_as_other=self.unkwown_types_as_other)

  async def _transactions_impl(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[Transaction]]:
    transactions: list[Transaction] = []
    async for chunk in self.spot_transactions(start, end):
      transactions.extend(chunk)
    async for chunk in self.future_transactions(start, end):
      transactions.extend(chunk)
    async for chunk in self.margin_transactions(start, end):
      transactions.extend(chunk)
    transactions = [self.add_tz(tx) for tx in transactions]
    parse_internal_transfers(transactions)
    yield transactions