from datetime import datetime, timedelta
from typing_extensions import AsyncIterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

# from tribulnation.sdk.wallet.deposit_history import Deposit, DepositHistory as DepositHistoryTDK
Deposit = dict
class _DepositHistory:
  ...

from mexc.core import timestamp
from mexc.spot.wallet.deposit_history import DepositHistory as Client, Status
from mexc_sdk.core import SdkMixin, wrap_exceptions

async def _deposit_history(
  client: Client, *, start: datetime, end: datetime, asset: str | None = None,
) -> list[Deposit]:
  deposits = await client.deposit_history(start=start, end=end, coin=asset)
  return [
    Deposit(
      id=d['txId'],
      address=d['address'],
      memo=d.get('memo'),
      amount=Decimal(d['amount']),
      asset=d['coin'],
      network=d['netWork'],
      time=timestamp.parse(d['insertTime']),
    )
    for d in deposits if d.get('status') == Status.success
  ]
    
async def _paginate_deposits_forward(
  client: Client, *, asset: str | None = None,
  start: datetime, end: datetime | None = None,
  delta: timedelta = timedelta(days=7),
) -> AsyncIterable[Sequence[Deposit]]:
  """Paginate deposits forwards from the `start`"""
  ids = set()
  end = end or datetime.now()
  while start < end:
    deposits = await _deposit_history(client, start=start, end=start + delta, asset=asset)
    new_deposits = [d for d in reversed(deposits) if d.id not in ids] # ordered by time
    if new_deposits:
      ids.update(d.id for d in new_deposits)
      yield new_deposits
      start = new_deposits[-1].time
    else:
      start += delta

# async def _paginate_deposits_backward(
#   client: Client, *, asset: str | None = None,
#   start: datetime | None = None, end: datetime,
#   delta: timedelta = timedelta(days=7),
# ) -> AsyncIterable[Sequence[Deposit]]:
#   """Paginate deposits backwards from the `end`"""
#   ids = set()
#   while start is None or start < end:
#     deposits = await _deposit_history(client, start=end-delta, end=end, asset=asset)
#     new_deposits = [d for d in deposits if d.id not in ids] # ordered backwards by time
#     if new_deposits:
#       ids.update(d.id for d in new_deposits)
#       yield new_deposits
#       end = new_deposits[-1].time
#     else:
#       end -= delta

@dataclass
class DepositHistory(_DepositHistory, SdkMixin):
  @wrap_exceptions
  async def deposit_history(
    self, *, asset: str | None = None,
    start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Deposit]]:
    async for deposits in _paginate_deposits_forward(self.client.spot, start=start, end=end, asset=asset):
      yield deposits
