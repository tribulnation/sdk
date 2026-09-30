"""Aster snapshots of the perp and spot wallets, and cash ledgers as unclassified
observations.

`ReportSDK` routes mainnet accounts for snapshots. Testnet snapshots are unsupported: its
spot `account.info` omits funded balances.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import asyncio
from typing_extensions import AsyncIterable, Collection
from typed_aster.chain.rpc.get_balance import ChainStakingSummary
from typed_aster.futures.account.balance import FuturesBalance
from typed_aster.futures.position.risk import PositionRisk
from typed_aster.schemas import AccountInfo
from tribulnation.sdk.reporting import (
  HistoryRecord,
  Position,
  Report as SDKReport,
  Snapshot,
  SnapshotRecord,
  SubaccountSnapshot,
  UnknownObservation,
)
from tribulnation.sdk.core import AuthError
from .core import Public

DEFAULT_LOOKBACK = timedelta(days=7)
PAGE = 1000


def perp_state(
  balances: list[FuturesBalance], risks: list[PositionRisk]
) -> SubaccountSnapshot:
  """Futures wallet balances, without unrealized PnL, and open positions by symbol.

  In hedge mode a symbol has a `LONG` and a `SHORT` leg, merged into one net position.
  """
  sides: dict[str, list[Position]] = {}
  for r in risks:
    if r['positionAmt']:
      sides.setdefault(r['symbol'], []).append(
        Position(size=r['positionAmt'], avg_price=r['entryPrice'])
      )
  return SubaccountSnapshot(
    subaccount='perp',
    balances={r['asset']: r['balance'] for r in balances if r['balance']},
    positions={symbol: Position.merge(legs) for symbol, legs in sides.items()},
  )


def spot_state(info: AccountInfo) -> SubaccountSnapshot:
  """Spot balances, locked parts included."""
  return SubaccountSnapshot(
    subaccount='spot',
    balances={
      b['asset']: b['free'] + b['locked']
      for b in info['balances']
      if b['free'] + b['locked']
    },
  )


STAKED_ASSET = 'ASTER'
"""Aster Chain stakes ASTER only."""


def staking_state(summary: ChainStakingSummary | None) -> SubaccountSnapshot:
  """ASTER staked on Aster Chain, still owned in every state, and unclaimed rewards.

  Active, pending and unstaking amounts are all held out of the spot and perp wallets
  until returned; rewards are claimable. The summary reports `null` for zero amounts.
  """
  balances: dict[str, Decimal] = {}
  summary = summary or {}
  for amount in (
    summary.get('totalStakedAmount'),
    summary.get('totalPendingStakeAmount'),
    summary.get('totalPendingUnstakeAmount'),
  ):
    if amount:
      balances[STAKED_ASSET] = balances.get(STAKED_ASSET, Decimal(0)) + amount
  for reward in summary.get('totalUnclaimedRewards') or []:
    if reward['amount']:
      asset = reward['asset']
      balances[asset] = balances.get(asset, Decimal(0)) + reward['amount']
  return SubaccountSnapshot(subaccount='staking', balances=balances)


@dataclass(frozen=True, kw_only=True)
class Report(Public, SDKReport):
  """Perp and spot wallet snapshots, and cash ledgers without classification."""

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    """The `perp` wallet and positions, the `spot` wallet, and Aster Chain `staking`.

    Args:
      assets: Ignored: the venue enumerates holdings.

    Raises:
      NotImplementedError: On testnet, whose spot `account.info` omits funded balances.
    """
    if not self.shared.mainnet:
      raise NotImplementedError(
        'Aster testnet snapshots are not supported: spot balances are missing'
      )
    credentials = self.client.futures.client.credentials
    if credentials is None:
      raise AuthError('Aster snapshots need `user` and `signer`')
    balances, risks, spot, chain = await asyncio.gather(
      self.shared.call(self.client.futures.account.balance),
      self.shared.call(self.client.futures.position.risk),
      self.shared.call(self.client.spot.account.info),
      self.shared.call(
        lambda: self.client.chain.rpc.get_balance(address=credentials.user)
      ),
    )
    snapshot = Snapshot(
      subaccounts=[
        perp_state(balances, risks),
        spot_state(spot),
        staking_state(chain.get('staking')),
      ]
    )
    return SnapshotRecord(
      snapshot=snapshot,
      provenance={
        'source': 'api',
        'service': self.venue_id,
        'id': snapshot.time.isoformat(),
      },
    )

  def record(
    self,
    *,
    subaccount: str,
    id: str,
    time: datetime,
    asset: str,
    amount: Decimal,
    details: object,
  ) -> HistoryRecord:
    """Wrap one native cash delta, identified by `subaccount:id`."""
    return HistoryRecord(
      observations=[
        UnknownObservation(
          id=id, time=time, subaccount=subaccount, asset=asset, amount=amount
        )
      ],
      provenance={
        'source': 'api',
        'service': self.venue_id,
        'id': f'{subaccount}:{id}',
        'details': details,
      },
    )

  async def history(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[HistoryRecord]:
    """Stream perpetual income, then spot transactions, as cash deltas.

    Args:
      start: Inclusive lower bound; defaults to seven days before `end`.
      end: Inclusive upper bound; defaults to now.
    """
    upper = end or datetime.now(timezone.utc)
    lower = start or upper - DEFAULT_LOOKBACK
    if lower.tzinfo is None or upper.tzinfo is None:
      raise ValueError('History bounds must be timezone-aware')
    if upper < lower:
      raise ValueError('History end precedes start')
    income = self.client.futures.account.income_paged(
      start_time=lower, end_time=upper, limit=PAGE
    )
    async for page in income.via(self.shared.call):
      for row in page:
        yield self.record(
          subaccount='perp',
          id=f'{row["incomeType"]}:{row["tranId"]}',
          time=row['time'],
          asset=row['asset'],
          amount=row['income'],
          details=row,
        )
    transactions = self.client.spot.account.transaction_history_paged(
      start_time=lower, end_time=upper, limit=PAGE
    )
    async for page in transactions.via(self.shared.call):
      for row in page:
        # One spot transaction ID spans several asset/type legs.
        yield self.record(
          subaccount='spot',
          id=f'{row["type"]}:{row["asset"]}:{row["tranId"]}',
          time=row['time'],
          asset=row['asset'],
          amount=row['balanceDelta'],
          details=row,
        )
