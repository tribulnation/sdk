"""Binance spot-side balances without futures account access."""

from typing_extensions import Collection
from dataclasses import dataclass
import asyncio

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import (
  Balances,
  Snapshot,
  SnapshotRecord,
  Snapshots as _Snapshots,
  SubaccountSnapshot,
)

from tribulnation.binance.core import SdkMixin
from .util import new_source_id

PAGE_SIZE = 100
"""Rows per page for the Simple Earn position cursors."""


def keep(assets: Collection[str] | None, asset: str) -> bool:
  """Whether an asset survives the caller's filter."""
  return assets is None or asset in assets


@dataclass
class Snapshots(SdkMixin, _Snapshots):
  """Binance Spot, Funding and Simple Earn balances.

  Each supported compartment is reported separately. Futures compartments are excluded,
  not represented as empty balances or positions.

  **Does not support**:
  - Cross and isolated margin balances (`spot.http.margin.account`).
  - USD-M and COIN-M futures, Options and Portfolio Margin balances and positions.
  - Soft Staking, On-chain Yields, BFUSD, RWUSD and ETH/SOL staking holdings, which sit
    outside the two Simple Earn position endpoints read below.
  """

  @SDK.method
  async def spot_balances(self, assets: Collection[str] | None = None) -> Balances:
    """Fetch Spot wallet balances."""
    account = await self.call_binance(
      lambda: self.client.spot.http.account.info(omit_zero_balances=True)
    )
    out = Balances()
    for balance in account['balances']:
      if keep(assets, balance['asset']):
        out[balance['asset']] += balance['free'] + balance['locked']
    return out

  @SDK.method
  async def funding_balances(self, assets: Collection[str] | None = None) -> Balances:
    """Fetch Funding wallet balances.

    A compartment of its own on Binance, separate from Spot, and holding whatever Pay,
    Card, Gift Card and Stock Token leave behind.
    """
    rows = await self.call_binance(
      lambda: self.client.spot.http.wallet.asset.funding_wallet()
    )
    out = Balances()
    for row in rows:
      if keep(assets, row['asset']):
        out[row['asset']] += (
          row['free'] + row['locked'] + row['freeze'] + row['withdrawing']
        )
    return out

  @SDK.method
  async def earn_balances(self, assets: Collection[str] | None = None) -> Balances:
    """Fetch Simple Earn holdings, flexible and locked."""
    out = Balances()
    flexible = self.client.spot.http.simple_earn.flexible.position_paged(
      size=PAGE_SIZE
    ).via(self.call_binance)
    async for chunk in flexible:
      for position in chunk:
        if keep(assets, position['asset']):
          out[position['asset']] += position['totalAmount']

    locked = self.client.spot.http.simple_earn.locked.position_paged(
      size=PAGE_SIZE
    ).via(self.call_binance)
    async for chunk in locked:
      for position in chunk:
        if keep(assets, position['asset']):
          out[position['asset']] += position['amount'] + position['redeemingAmt']
    return out

  @SDK.method
  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    """Fetch only Spot, Funding and Simple Earn; supported-source failures propagate."""
    results = await asyncio.gather(
      self.spot_balances(assets),
      self.funding_balances(assets),
      self.earn_balances(assets),
      return_exceptions=True,
    )
    states: list[SubaccountSnapshot] = []
    for compartment, result in zip(('spot', 'funding', 'earn'), results):
      if isinstance(result, BaseException):
        raise result
      states.append(SubaccountSnapshot(subaccount=compartment, balances=result))
    return SnapshotRecord(
      snapshot=Snapshot(subaccounts=states),
      provenance={'source': 'api', 'service': 'binance', 'id': new_source_id()},
    )
