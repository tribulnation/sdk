"""Binance balances and positions, across the wallet compartments they live in."""

from typing_extensions import Awaitable, Collection, TypeVar
from dataclasses import dataclass
from decimal import Decimal
import asyncio

from tribulnation.sdk.core import SDK, AuthError
from tribulnation.sdk.reporting import (
  Balances,
  Position,
  Snapshot,
  SnapshotRecord,
  Snapshots as _Snapshots,
  SubaccountSnapshot,
)

from tribulnation.binance.core import SdkMixin
from .util import new_source_id, raise_if_all_failed

T = TypeVar('T')

PAGE_SIZE = 100
"""Rows per page for the Simple Earn position cursors."""


def keep(assets: Collection[str] | None, asset: str) -> bool:
  """Whether an asset survives the caller's filter."""
  return assets is None or asset in assets


@dataclass
class Snapshots(SdkMixin, _Snapshots):
  """Binance balances and positions.

  Covers the Spot, Funding, Simple Earn and USD-M futures compartments, each reported as
  its own subaccount.

  **Does not support**:
  - Cross and isolated margin balances (`spot.http.margin.account`).
  - COIN-M futures, Options and Portfolio Margin balances and positions.
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
    flexible = self.client.spot.http.simple_earn.flexible.position_paged(size=PAGE_SIZE)
    state = flexible.init
    while state is not None:
      chunk, state = await self.call_binance(lambda: flexible.next(state))  # type: ignore
      for position in chunk:
        if keep(assets, position['asset']):
          out[position['asset']] += Decimal(position['totalAmount'])

    locked = self.client.spot.http.simple_earn.locked.position_paged(size=PAGE_SIZE)
    state = locked.init
    while state is not None:
      chunk, state = await self.call_binance(lambda: locked.next(state))  # type: ignore
      for position in chunk:
        if keep(assets, position['asset']):
          out[position['asset']] += Decimal(position['amount']) + Decimal(
            position['redeemingAmt']
          )
    return out

  @SDK.method
  async def usdm_balances(self, assets: Collection[str] | None = None) -> Balances:
    """Fetch USD-M futures wallet balances."""
    account = await self.call_binance(
      lambda: self.client.usdm_futures.http.account.account_v3()
    )
    out = Balances()
    for row in account.get('assets') or []:
      asset = row.get('asset')
      balance = row.get('walletBalance')
      if asset is not None and balance is not None and keep(assets, asset):
        out[asset] += Decimal(balance)
    return out

  @SDK.method
  async def usdm_positions(self) -> dict[str, Position]:
    """Fetch open USD-M futures positions, keyed by symbol."""
    rows = await self.call_binance(
      lambda: self.client.usdm_futures.http.trading.position_risk_v3()
    )
    out: dict[str, Position] = {}
    for row in rows:
      size = Decimal(row['positionAmt'])
      if size == 0:
        continue
      out[row['symbol']] = Position(
        size=size, avg_price=Decimal(row.get('entryPrice') or 0)
      )
    return out

  @SDK.method
  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    """Fetch the account's current balances and positions.

    A compartment whose endpoint raises `AuthError` contributes nothing rather than
    failing the whole snapshot -- Binance gates Futures behind its own API-key flag, so
    a spot-only key is a normal configuration, not an outage. If every compartment
    raises one, the credentials are bad and the error propagates.
    """
    failures: list[AuthError] = []

    async def guarded(call: Awaitable[T], empty: T) -> T:
      try:
        return await call
      except AuthError as e:
        failures.append(e)
        return empty

    spot, funding, earn, usdm, positions = await asyncio.gather(
      guarded(self.spot_balances(assets), Balances()),
      guarded(self.funding_balances(assets), Balances()),
      guarded(self.earn_balances(assets), Balances()),
      guarded(self.usdm_balances(assets), Balances()),
      guarded(self.usdm_positions(), {}),
    )
    raise_if_all_failed(failures, 5)

    return SnapshotRecord(
      snapshot=Snapshot(
        subaccounts=[
          SubaccountSnapshot(subaccount='spot', balances=spot),
          SubaccountSnapshot(subaccount='funding', balances=funding),
          SubaccountSnapshot(subaccount='earn', balances=earn),
          SubaccountSnapshot(
            subaccount='usdm_futures', balances=usdm, positions=positions
          ),
        ]
      ),
      provenance={'source': 'api', 'service': 'binance', 'id': new_source_id()},
    )
