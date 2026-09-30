"""Lighter account snapshots, read by L1 address without credentials.

`history()` is not supported: the Report history surface is being retired.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import asyncio

from typing_extensions import AsyncContextManager, AsyncIterable, Collection, Iterable
from typed_lighter.api.account.get import DetailedAccount
from typed_lighter.core.networks import Network
from tribulnation.sdk.reporting import (
  HistoryRecord,
  Position,
  Report as SDKReport,
  Snapshot,
  SnapshotRecord,
  SubaccountSnapshot,
)

from .core import USDC, Shared
from .market.account import ISOLATED


def holdings(acct: DetailedAccount) -> dict[str, Decimal]:
  """An account's balances, without unrealized PnL.

  `balance` is the spot holding (locked part included) and `margin_balance` the perps
  collateral; classic accounts hold USDC in both, unified accounts in the latter only.
  Each isolated position's `allocated_margin` is USDC held beside the cross collateral.
  """
  balances = {
    str(a['asset_id']): a['balance'] + a['margin_balance'] for a in acct['assets']
  }
  isolated = sum(
    (p['allocated_margin'] for p in acct['positions'] if p['margin_mode'] == ISOLATED),
    Decimal(0),
  )
  balances[str(USDC)] = balances.get(str(USDC), Decimal(0)) + isolated
  return {asset: qty for asset, qty in balances.items() if qty}


def positions(acct: DetailedAccount) -> dict[str, Position]:
  """Open positions by market id, signed (`position` is unsigned beside `sign`)."""
  return {
    str(p['market_id']): Position(
      size=p['sign'] * p['position'], avg_price=p['avg_entry_price']
    )
    for p in acct['positions']
    if p['position']
  }


def pool_claim(pool: DetailedAccount, shares: int) -> dict[str, Decimal]:
  """A holder's pro-rata part of a pool account, in the pool's native assets.

  A pool's `total_asset_value` is its USDC equity, unrealized PnL included, but leaves
  out its non-USDC balances (the LLP's ETH, XAUT, ...), which are added as held. Priced
  at spot, an LLP claim matched the holder's pool value on the venue's PnL chart.
  """
  info = pool.get('pool_info')
  if info is None:
    raise ValueError(f'Lighter account {pool["index"]} is not a pool')
  fraction = Decimal(shares) / Decimal(info['total_shares'])
  held = {
    str(a['asset_id']): a['balance']
    + (a['margin_balance'] if a['asset_id'] != USDC else Decimal(0))
    for a in pool['assets']
  }
  held[str(USDC)] = held.get(str(USDC), Decimal(0)) + pool['total_asset_value']
  return {asset: fraction * qty for asset, qty in held.items() if qty}


def unlocking(acct: DetailedAccount) -> dict[str, Decimal]:
  """Unstaked assets still in their lockup."""
  balances: dict[str, Decimal] = {}
  for unlock in acct['pending_unlocks']:
    if 'asset_index' in unlock and 'amount' in unlock:
      asset = str(unlock['asset_index'])
      balances[asset] = balances.get(asset, Decimal(0)) + unlock['amount']
  return {asset: qty for asset, qty in balances.items() if qty}


def account_snapshots(
  acct: DetailedAccount, pools: dict[int, DetailedAccount]
) -> list[SubaccountSnapshot]:
  """One account's compartments: `<index>`, `<index>:pool:<pool>`, `<index>:unlocking`.

  A pool the address operates is listed among its accounts, but its holdings belong to
  every shareholder: only the operator's shares (`<pool>:operator`) are the address's,
  and they appear in no account's `shares`.
  """
  index = acct['index']
  if (info := acct.get('pool_info')) is not None:
    return [
      SubaccountSnapshot(
        subaccount=f'{index}:operator',
        balances=pool_claim(acct, info['operator_shares']),
      )
    ]
  states = [
    SubaccountSnapshot(
      subaccount=str(index), balances=holdings(acct), positions=positions(acct)
    )
  ]
  for share in acct['shares']:
    pool = share['public_pool_index']
    states.append(
      SubaccountSnapshot(
        subaccount=f'{index}:pool:{pool}',
        balances=pool_claim(pools[pool], share['shares_amount']),
      )
    )
  if pending := unlocking(acct):
    states.append(SubaccountSnapshot(subaccount=f'{index}:unlocking', balances=pending))
  return states


@dataclass(frozen=True, kw_only=True)
class Report(SDKReport):
  """Snapshots of every account (master and sub-accounts) of one L1 address."""

  shared: Shared
  owner: str | int
  """The L1 address, or the index of one of its accounts to resolve it from."""
  network: Network = 'mainnet'

  @classmethod
  def new(
    cls, owner: str | int, *, network: Network = 'mainnet', validate: bool = True
  ):
    """Create a credential-free report over a new client.

    Args:
      owner: L1 (Ethereum) address owning the accounts, or the index of any one of
        them, whose address is then looked up on every snapshot.
      network: Lighter deployment.
      validate: Validate responses.
    """
    return cls(
      shared=Shared.new(network=network, public=True, validate=validate),
      owner=owner,
      network=network,
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """Enter the shared owner through the SDK lifecycle."""
    yield self.shared

  async def account(self, index: int) -> DetailedAccount:
    """One account by index; every account is public."""
    response = await self.shared.call(
      lambda: self.shared.client.api.account.get({'by': 'index', 'value': index})
    )
    return response['accounts'][0]

  async def address(self) -> str:
    """The owner's L1 address, looked up when given an account index."""
    if isinstance(self.owner, str):
      return self.owner
    return (await self.account(self.owner))['l1_address']

  async def accounts(self) -> list[DetailedAccount]:
    """Every account of the address."""
    address = await self.address()
    response = await self.shared.call(
      lambda: self.shared.client.api.account.get({'by': 'l1_address', 'value': address})
    )
    return response['accounts']

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    """Balances, positions and pool claims of every account of the address.

    Args:
      assets: Ignored: the venue enumerates holdings.
    """
    accounts = await self.accounts()
    ids = sorted({s['public_pool_index'] for a in accounts for s in a['shares']})
    pools = dict(zip(ids, await asyncio.gather(*map(self.account, ids))))
    snapshot = Snapshot(
      subaccounts=[state for a in accounts for state in account_snapshots(a, pools)]
    )
    return SnapshotRecord(
      snapshot=snapshot,
      provenance={
        'source': 'api',
        'service': 'lighter' if self.network == 'mainnet' else 'lighter_testnet',
        'id': snapshot.time.isoformat(),
      },
    )

  async def history(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[HistoryRecord]:
    """Unsupported: the Report history surface is being retired."""
    raise NotImplementedError('Lighter report history is not supported')
    yield
