from datetime import datetime, timedelta
from typing_extensions import AsyncIterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

Withdrawal = dict
class _WithdrawalHistory:
  ...
# from tribulnation.sdk.wallet.withdrawal_history import Withdrawal, WithdrawalHistory as _WithdrawalHistory

from mexc.core import timestamp
from mexc.spot.wallet.withdrawal_history import WithdrawalHistory as Client, Status
from mexc_sdk.core import SdkMixin, wrap_exceptions

async def _withdrawal_history(
  client: Client, *, asset: str | None = None,
  start: datetime, end: datetime,
) -> list[Withdrawal]:
  withdrawals = await client.withdrawal_history(start=start, end=end, coin=asset)
  return [
    Withdrawal(
      id=w['id'],
      address=w['address'],
      memo=w.get('memo'),
      amount=Decimal(w['amount']),
      asset=w['coin'],
      network=w['netWork'],
      time=timestamp.parse(w['applyTime']),
      fee=Withdrawal.Fee(
        asset=w['coin'],
        amount=Decimal(w['transactionFee']),
      ) if w.get('transactionFee') else None,
    )
    for w in withdrawals if w.get('status') == Status.success
  ]
    
async def _paginate_withdrawals_forward(
  client: Client, *, asset: str | None = None,
  start: datetime, end: datetime | None = None,
  delta: timedelta = timedelta(days=7),
) -> AsyncIterable[Sequence[Withdrawal]]:
  """Paginate withdrawals forwards from the `start`"""
  ids = set()
  end = end or datetime.now()
  while start < end:
    withdrawals = await _withdrawal_history(client, start=start, end=start + delta, asset=asset)
    new_withdrawals = [w for w in reversed(withdrawals) if w.id not in ids] # ordered by time
    if new_withdrawals:
      ids.update(w.id for w in new_withdrawals)
      yield new_withdrawals
      start = new_withdrawals[-1].time
    else:
      start += delta

# async def _paginate_withdrawals_backward(
#   client: Client, *, asset: str | None = None,
#   start: datetime | None = None, end: datetime,
#   delta: timedelta = timedelta(days=7),
# ) -> AsyncIterable[Sequence[Withdrawal]]:
#   """Paginate withdrawals backwards from the `end`"""
#   ids = set()
#   while start is None or start < end:
#     withdrawals = await _withdrawal_history(client, start=end-delta, end=end, asset=asset)
#     new_withdrawals = [w for w in withdrawals if w.id not in ids] # ordered backwards by time
#     if new_withdrawals:
#       ids.update(w.id for w in new_withdrawals)
#       yield new_withdrawals
#       end = new_withdrawals[-1].time
#     else:
#       end -= delta

@dataclass
class WithdrawalHistory(_WithdrawalHistory, SdkMixin):
  @wrap_exceptions
  async def withdrawal_history(
    self, *, asset: str | None = None,
    start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Withdrawal]]:
    async for withdrawals in _paginate_withdrawals_forward(self.client.spot, start=start, end=end, asset=asset):
      yield withdrawals
