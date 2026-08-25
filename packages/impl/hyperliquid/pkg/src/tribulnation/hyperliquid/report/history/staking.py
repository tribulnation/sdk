"""Staking rewards and delegation history.

Neither endpoint accepts a time range or paginates, so both return the account's
full history and are filtered client-side.
"""

from typing_extensions import Any, Iterable, Mapping
from decimal import Decimal

from tribulnation.sdk.reporting import InternalTransfer, Observation, Yield
from typed_hyperliquid.info.staking_rewards import DelegatorReward
from typed_hyperliquid.info.staking_history import DelegatorHistoryEvent

from ..subaccounts import STAKING, UNIFIED
from .assets import HYPE
from .window import parse_time


def parse_reward(reward: DelegatorReward, *, index: int) -> Yield:
  """Convert a staking reward into a yield observation.

  Scoped to the `staking` subaccount, not the spot wallet. Rewards accrue
  directly to the staked balance and only reach spot via a later withdrawal,
  which is reported separately as an internal transfer. Attributing them to spot
  would double-count: once on accrual, once on the transfer out.
  """
  return Yield(
    id=f'staking-reward:{reward["time"]}:{index}',
    time=parse_time(reward['time']),
    subaccount=STAKING,
    asset=HYPE,
    amount=Decimal(str(reward['totalAmount'])),
  )


def parse_rewards(rewards: Iterable[DelegatorReward]) -> list[Yield]:
  """Convert the staking reward stream into observations."""
  return [parse_reward(r, index=i) for i, r in enumerate(rewards)]


def parse_history_entry(
  entry: DelegatorHistoryEvent,
  *,
  index: int,
) -> list[Observation]:
  """Convert one staking history record into observations.

  The delta is a three-way union identified by which key is present, not by a
  `type` tag. `finalized` withdrawals carry an all-zero hash because
  finalization is a chain event with no user transaction, so the id folds in the
  response index rather than trusting the hash.
  """
  id = f'staking:{entry.get("hash", "")}:{index}'
  time = parse_time(entry['time'])
  delta: Mapping[str, Any] = entry['delta']

  if (delegate := delta.get('delegate')) is not None:
    undelegate = bool(delegate['isUndelegate'])
    return [
      InternalTransfer(
        id=id,
        time=time,
        asset=HYPE,
        amount=abs(Decimal(str(delegate['amount']))),
        src_account=delegate['validator'] if undelegate else STAKING,
        dst_account=STAKING if undelegate else delegate['validator'],
      )
    ]

  if (withdrawal := delta.get('withdrawal')) is not None:
    # Reported twice, once per phase. Only the finalized leg moves the balance;
    # emitting both would double-count.
    if withdrawal['phase'] != 'finalized':
      return []
    return [
      InternalTransfer(
        id=id,
        time=time,
        asset=HYPE,
        amount=abs(Decimal(str(withdrawal['amount']))),
        src_account=STAKING,
        dst_account=UNIFIED,
      )
    ]

  if (deposit := delta.get('cDeposit')) is not None:
    return [
      InternalTransfer(
        id=id,
        time=time,
        asset=HYPE,
        amount=abs(Decimal(str(deposit['amount']))),
        src_account=UNIFIED,
        dst_account=STAKING,
      )
    ]

  return []


def parse_history(entries: Iterable[DelegatorHistoryEvent]) -> list[Observation]:
  """Convert the staking history stream into observations."""
  return [
    obs
    for index, entry in enumerate(entries)
    for obs in parse_history_entry(entry, index=index)
  ]
