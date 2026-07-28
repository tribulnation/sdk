"""Non-funding ledger deltas mapped onto SDK observations.

Hyperliquid ships new delta types over time — four of the twenty modelled here
appear in no official documentation. `typed-hyperliquid` raises on an
unrecognised type, which is right for a typed client but wrong for a history
read: one unknown row must not abort an entire report. So deltas are fetched
unvalidated and validated individually, and a failure becomes an
`UnknownObservation` carrying the raw payload. The unknown stays visible in the
output instead of being silently dropped.
"""
from typing_extensions import Any, Mapping
from decimal import Decimal
import pydantic

from tribulnation.sdk.reporting import (
  Borrow, Bonus, CryptoDeposit, CryptoWithdrawal, Fee, FeeLeg, InternalTransfer,
  Observation, Repay, Transfer, UnknownObservation, Yield,
)
from hyperliquid.info.perps.user_non_funding_ledger_updates import (
  LedgerDelta, UserNonFundingLedgerEntry,
)

from .assets import Assets, HYPE, USDC
from .window import parse_time

delta_adapter = pydantic.TypeAdapter(LedgerDelta)

UNIFIED = 'unified'
"""Subaccount label for the main balance, matching `report/snapshots.py`."""

STAKING = 'staking'
"""Subaccount label for staked balance, matching `report/snapshots.py`."""

D = lambda v: Decimal(str(v))


def entry_id(entry: Mapping[str, Any], index: int) -> str:
  """Build a stable identifier for a ledger entry.

  `(time, hash)` is **not** unique: one transaction can emit several deltas, one
  per margin bucket. Two liquidation deltas sharing a timestamp and hash with
  different bodies have been observed. Deduplicating on hash drops rows, so the
  index within the response is folded in.
  """
  return f'ledger:{entry.get("hash", "")}:{index}'


def parse_delta(
  delta: Any, *, id: str, time, address: str, assets: Assets,
) -> list[Observation]:
  """Map one validated ledger delta onto zero or more observations."""
  kind = delta['type']
  mine = str(delta.get('user', '')).lower() == address.lower()
  base = {'id': id, 'time': time}

  if kind == 'deposit':
    return [CryptoDeposit(**base, asset=USDC, amount=D(delta['usdc']))]

  if kind == 'withdraw':
    return [CryptoWithdrawal(
      **base, asset=USDC, amount=D(delta['usdc']),
      fee=Fee(asset=USDC, amount=D(delta['fee'])),
    )]

  if kind in ('spotTransfer', 'send'):
    token = assets.token(delta['token'])
    amount = D(delta['amount'])
    out: list[Observation] = [Transfer(
      **base, asset=token, amount=-amount if mine else amount,
      src_account=delta.get('user'), dst_account=delta.get('destination'),
      fee=Fee(asset=assets.token(delta['feeToken'] or 'USDC'), amount=D(delta['fee']))
        if mine and D(delta['fee']) else None,
    )]
    # A HYPE-denominated fee charged on top of `fee`, in a separate field.
    if mine and (native := D(delta.get('nativeTokenFee', 0))):
      out.append(FeeLeg(**base, asset=HYPE, amount=native, event_type='transfer'))
    return out

  if kind in ('internalTransfer', 'subAccountTransfer'):
    amount = D(delta['usdc'])
    out = [InternalTransfer(
      **base, asset=USDC, amount=abs(amount),
      src_account=delta.get('user'), dst_account=delta.get('destination'),
    )]
    if mine and (fee := D(delta.get('fee', 0))):
      out.append(FeeLeg(**base, asset=USDC, amount=fee, event_type='internal_transfer'))
    return out

  if kind == 'accountClassTransfer':
    to_perp = bool(delta['toPerp'])
    return [InternalTransfer(
      **base, asset=USDC, amount=abs(D(delta['usdc'])),
      src_account='spot' if to_perp else 'perp',
      dst_account='perp' if to_perp else 'spot',
    )]

  if kind == 'cStakingTransfer':
    deposit = bool(delta['isDeposit'])
    return [InternalTransfer(
      **base, asset=assets.token(delta['token']), amount=abs(D(delta['amount'])),
      src_account=UNIFIED if deposit else STAKING,
      dst_account=STAKING if deposit else UNIFIED,
    )]

  if kind == 'vaultCreate':
    out = [InternalTransfer(
      **base, asset=USDC, amount=abs(D(delta['usdc'])),
      src_account=UNIFIED, dst_account=delta.get('vault'),
    )]
    if (fee := D(delta.get('fee', 0))):
      out.append(FeeLeg(**base, asset=USDC, amount=fee, event_type='internal_transfer'))
    return out

  if kind == 'vaultDeposit':
    return [InternalTransfer(
      **base, asset=USDC, amount=abs(D(delta['usdc'])),
      src_account=UNIFIED, dst_account=delta.get('vault'),
    )]

  if kind == 'vaultWithdraw':
    out = [InternalTransfer(
      **base, asset=USDC, amount=abs(D(delta['netWithdrawnUsd'])),
      src_account=delta.get('vault'), dst_account=UNIFIED,
    )]
    for field, label in (('commission', 'commission'), ('closingCost', 'closing cost')):
      if (amount := D(delta.get(field, 0))):
        out.append(FeeLeg(**base, asset=USDC, amount=amount, event_type='internal_transfer'))
    return out

  if kind == 'vaultDistribution':
    return [Yield(**base, asset=USDC, amount=D(delta['usdc']))]

  if kind == 'vaultLeaderCommission':
    return [Yield(**base, asset=USDC, amount=D(delta['usdc']))]

  if kind == 'spotGenesis':
    return [Bonus(
      **base, asset=assets.token(delta['token']), amount=D(delta['amount']),
      category='spotGenesis',
    )]

  if kind == 'rewardsClaim':
    # `token` may be the empty string on legacy USDC claims.
    return [Yield(
      **base, asset=assets.token(delta['token'] or 'USDC'), amount=D(delta['amount']),
    )]

  if kind == 'borrowLend':
    token = assets.token(delta['token'])
    amount, interest = D(delta['amount']), D(delta.get('interestAmount', 0))
    out = []
    if delta['operation'] == 'supply':
      out.append(Repay(**base, asset=token, amount=amount))
    else:
      out.append(Borrow(**base, asset=token, amount=amount))
    if interest:
      out.append(Yield(**base, asset=token, amount=interest))
    return out

  if kind in ('activateDexAbstraction', 'accountActivationGas', 'deployGasAuction'):
    return [FeeLeg(
      **base, asset=assets.token(delta['token']), amount=D(delta['amount']),
      event_type='unknown',
    )]

  if kind == 'liquidation':
    # No balance impact of its own: the positions are closed by fills tagged
    # `dir: 'Liquidated …'`, which the fill stream already carries. Verified
    # that those fills exactly offset the reported `liquidatedPositions`.
    return []

  return [UnknownObservation(**base, asset=USDC, amount=Decimal(0))]


def parse_entry(
  entry: UserNonFundingLedgerEntry, *, index: int, address: str, assets: Assets,
) -> list[Observation]:
  """Map one raw ledger entry onto observations, tolerating unknown types."""
  id = entry_id(entry, index)
  time = parse_time(entry['time'])
  raw = entry['delta']
  try:
    delta = delta_adapter.validate_python(raw)
  except pydantic.ValidationError:
    # A type this client does not model yet. Surface it rather than drop it.
    return [UnknownObservation(
      id=f'{id}:0', time=time, asset=USDC, amount=Decimal(0),
    )]
  observations = parse_delta(delta, id=id, time=time, address=address, assets=assets)
  # One delta can yield several observations — a transfer plus its fee leg, or a
  # borrow plus accrued interest — and they must not share an identifier.
  return [
    obs.model_copy(update={'id': f'{id}:{n}'})
    for n, obs in enumerate(observations)
  ]
