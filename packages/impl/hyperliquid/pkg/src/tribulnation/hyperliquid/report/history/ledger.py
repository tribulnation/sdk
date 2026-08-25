"""Non-funding ledger deltas mapped onto SDK observations.

Hyperliquid ships new delta types over time — four of the twenty modelled here
appear in no official documentation. `typed-hyperliquid` raises on an
unrecognised type, which is right for a typed client but wrong for a history
read: one unknown row must not abort an entire report. So deltas are fetched
unvalidated and validated individually, and a failure becomes an
`UnknownObservation` carrying the raw payload. The unknown stays visible in the
output instead of being silently dropped.
"""

from typing_extensions import Any, Mapping, TypeAlias
from decimal import Decimal
import pydantic

from tribulnation.sdk.reporting import (
  Borrow,
  Bonus,
  CryptoDeposit,
  CryptoWithdrawal,
  Fee,
  FeeLeg,
  InternalTransfer,
  Observation,
  Repay,
  Transfer,
  UnknownObservation,
  Yield,
)
from typed_hyperliquid.info.user_non_funding_ledger_updates import (
  AccountActivationGasDelta,
  AccountClassTransferDelta,
  ActivateDexAbstractionDelta,
  BorrowLendDelta,
  CstakingTransferDelta,
  DeployGasAuctionDelta,
  DepositDelta,
  InternalTransferDelta,
  LiquidationDelta,
  RewardsClaimDelta,
  SendDelta,
  SpotGenesisDelta,
  SpotTransferDelta,
  SubAccountTransferDelta,
  UserNonFundingLedgerEntry,
  VaultCreateDelta,
  VaultDepositDelta,
  VaultDistributionDelta,
  VaultLeaderCommissionDelta,
  VaultWithdrawDelta,
  WithdrawDelta,
)

from ..subaccounts import STAKING, UNIFIED
from .assets import Assets, HYPE, USDC
from .window import parse_time

LedgerDelta: TypeAlias = (
  AccountActivationGasDelta
  | AccountClassTransferDelta
  | ActivateDexAbstractionDelta
  | BorrowLendDelta
  | CstakingTransferDelta
  | DeployGasAuctionDelta
  | DepositDelta
  | InternalTransferDelta
  | LiquidationDelta
  | RewardsClaimDelta
  | SendDelta
  | SpotGenesisDelta
  | SpotTransferDelta
  | SubAccountTransferDelta
  | VaultCreateDelta
  | VaultDepositDelta
  | VaultDistributionDelta
  | VaultLeaderCommissionDelta
  | VaultWithdrawDelta
  | WithdrawDelta
)

delta_adapter = pydantic.TypeAdapter(LedgerDelta)

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
  delta: LedgerDelta,
  *,
  id: str,
  time,
  address: str,
  assets: Assets,
) -> list[Observation]:
  """Map one validated ledger delta onto zero or more observations."""
  mine = str(delta.get('user', '')).lower() == address.lower()
  # Every ledger delta acts on the main pool. Staking is reached only through
  # `cStakingTransfer`, which names both compartments in `src`/`dst` instead.
  base = {'id': id, 'time': time, 'subaccount': UNIFIED}

  if delta['type'] == 'deposit':
    return [CryptoDeposit(**base, asset=USDC, amount=D(delta['usdc']))]

  if delta['type'] == 'withdraw':
    return [
      CryptoWithdrawal(
        **base,
        asset=USDC,
        amount=D(delta['usdc']),
        fee=Fee(asset=USDC, amount=D(delta['fee'])),
      )
    ]

  if delta['type'] == 'spotTransfer' or delta['type'] == 'send':
    token = assets.token(delta['token'])
    amount = D(delta['amount'])
    out: list[Observation] = [
      Transfer(
        **base,
        asset=token,
        amount=-amount if mine else amount,
        src_account=delta.get('user'),
        dst_account=delta.get('destination'),
        fee=Fee(asset=assets.token(delta['feeToken'] or 'USDC'), amount=D(delta['fee']))
        if mine and D(delta['fee'])
        else None,
      )
    ]
    # A HYPE-denominated fee charged on top of `fee`, in a separate field.
    if mine and (native := D(delta.get('nativeTokenFee', 0))):
      out.append(FeeLeg(**base, asset=HYPE, amount=native, event_type='transfer'))
    return out

  if delta['type'] == 'internalTransfer' or delta['type'] == 'subAccountTransfer':
    amount = D(delta['usdc'])
    out = [
      InternalTransfer(
        **base,
        asset=USDC,
        amount=abs(amount),
        src_account=delta.get('user'),
        dst_account=delta.get('destination'),
      )
    ]
    if mine and (fee := D(delta.get('fee', 0))):
      out.append(FeeLeg(**base, asset=USDC, amount=fee, event_type='internal_transfer'))
    return out

  if delta['type'] == 'accountClassTransfer':
    to_perp = bool(delta['toPerp'])
    return [
      InternalTransfer(
        **base,
        asset=USDC,
        amount=abs(D(delta['usdc'])),
        src_account='spot' if to_perp else 'perp',
        dst_account='perp' if to_perp else 'spot',
      )
    ]

  if delta['type'] == 'cStakingTransfer':
    deposit = bool(delta['isDeposit'])
    return [
      InternalTransfer(
        **base,
        asset=assets.token(delta['token']),
        amount=abs(D(delta['amount'])),
        src_account=UNIFIED if deposit else STAKING,
        dst_account=STAKING if deposit else UNIFIED,
      )
    ]

  if delta['type'] == 'vaultCreate':
    out = [
      InternalTransfer(
        **base,
        asset=USDC,
        amount=abs(D(delta['usdc'])),
        src_account=UNIFIED,
        dst_account=delta.get('vault'),
      )
    ]
    if fee := D(delta.get('fee', 0)):
      out.append(FeeLeg(**base, asset=USDC, amount=fee, event_type='internal_transfer'))
    return out

  if delta['type'] == 'vaultDeposit':
    return [
      InternalTransfer(
        **base,
        asset=USDC,
        amount=abs(D(delta['usdc'])),
        src_account=UNIFIED,
        dst_account=delta.get('vault'),
      )
    ]

  if delta['type'] == 'vaultWithdraw':
    out = [
      InternalTransfer(
        **base,
        asset=USDC,
        amount=abs(D(delta['netWithdrawnUsd'])),
        src_account=delta.get('vault'),
        dst_account=UNIFIED,
      )
    ]
    for field, label in (('commission', 'commission'), ('closingCost', 'closing cost')):
      if amount := D(delta.get(field, 0)):
        out.append(
          FeeLeg(**base, asset=USDC, amount=amount, event_type='internal_transfer')
        )
    return out

  if delta['type'] == 'vaultDistribution':
    return [Yield(**base, asset=USDC, amount=D(delta['usdc']))]

  if delta['type'] == 'vaultLeaderCommission':
    return [Yield(**base, asset=USDC, amount=D(delta['usdc']))]

  if delta['type'] == 'spotGenesis':
    return [
      Bonus(
        **base,
        asset=assets.token(delta['token']),
        amount=D(delta['amount']),
        category='spotGenesis',
      )
    ]

  if delta['type'] == 'rewardsClaim':
    # `token` may be the empty string on legacy USDC claims.
    return [
      Yield(
        **base,
        asset=assets.token(delta['token'] or 'USDC'),
        amount=D(delta['amount']),
      )
    ]

  if delta['type'] == 'borrowLend':
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

  if (
    delta['type'] == 'activateDexAbstraction'
    or delta['type'] == 'accountActivationGas'
    or delta['type'] == 'deployGasAuction'
  ):
    return [
      FeeLeg(
        **base,
        asset=assets.token(delta['token']),
        amount=D(delta['amount']),
        event_type='unknown',
      )
    ]

  if delta['type'] == 'liquidation':
    # No balance impact of its own: the positions are closed by fills tagged
    # `dir: 'Liquidated …'`, which the fill stream already carries. Verified
    # that those fills exactly offset the reported `liquidatedPositions`.
    return []

  return [UnknownObservation(**base, asset=USDC, amount=Decimal(0))]


def parse_entry(
  entry: UserNonFundingLedgerEntry,
  *,
  index: int,
  address: str,
  assets: Assets,
) -> list[Observation]:
  """Map one raw ledger entry onto observations, tolerating unknown types."""
  id = entry_id(entry, index)
  time = parse_time(entry['time'])
  raw = entry['delta']
  try:
    delta = delta_adapter.validate_python(raw)
  except pydantic.ValidationError:
    # A type this client does not model yet. Surface it rather than drop it.
    return [
      UnknownObservation(
        id=f'{id}:0',
        time=time,
        asset=USDC,
        amount=Decimal(0),
      )
    ]
  observations = parse_delta(delta, id=id, time=time, address=address, assets=assets)
  # One delta can yield several observations — a transfer plus its fee leg, or a
  # borrow plus accrued interest — and they must not share an identifier.
  return [
    obs.model_copy(update={'id': f'{id}:{n}'}) for n, obs in enumerate(observations)
  ]
