"""Bit2Me implementation of the `snapshot` reporting endpoint."""

from typing_extensions import Collection
from dataclasses import dataclass
from decimal import Decimal
import asyncio

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import (
  Balances,
  Snapshot,
  SnapshotRecord,
  Snapshots as _Snapshots,
  SubaccountSnapshot,
  source_id,
)
from tribulnation.bit2me.core import Mixin

EARN_WALLETS_PAGE = 100
"""Earn wallets fetched per page. One page holds every wallet an account has in
practice; the walk below still pages, since the endpoint reports a `total`."""


@dataclass(frozen=True, kw_only=True)
class Snapshots(_Snapshots, Mixin):
  """Bit2Me implementation of `Snapshots`.

  Bit2Me splits balances across three sub-products with no shared ledger: the
  Trading Spot wallet, Earn, and Wallet pockets. Funds cross between them only
  through explicit transfers (`/v1/trading/wallet/{deposit,withdraw}` between spot
  and pockets, `/v1/earn/movements` between earn and pockets), so they are not three
  views of one balance and each becomes its own `SubaccountSnapshot`.
  """

  @SDK.method
  async def spot_balances(self) -> Balances:
    """Balances held in the Trading Spot wallet, including amounts blocked in orders."""
    out = Balances()
    for entry in await self.call_bit2me(self.client.v1.trading.balance):
      out[entry['currency']] += Decimal(str(entry['balance'])) + Decimal(
        str(entry['blockedBalance'])
      )
    return out

  @SDK.method
  async def earn_balances(self) -> Balances:
    """Balances held in Earn wallets."""
    out = Balances()
    offset = 0
    while True:
      current = offset
      page = await self.call_bit2me(
        lambda: self.client.v2.earn.wallets(offset=current, limit=EARN_WALLETS_PAGE)
      )
      entries = page.get('data', [])
      for entry in entries:
        out[entry['currency']] += Decimal(str(entry['balance']))
      offset += len(entries)
      if not entries or offset >= (page.get('total') or 0):
        return out

  @SDK.method
  async def pocket_balances(self) -> Balances:
    """Balances held in Bit2Me Wallet pockets, including blocked amounts."""
    out = Balances()
    for entry in await self.call_bit2me(self.client.v1.wallet.pockets.get):
      out[entry['currency']] += Decimal(str(entry['balance'])) + Decimal(
        str(entry['blockedBalance'])
      )
    return out

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    """Fetch the account's balances across all three compartments.

    Args:
      assets: Ignored. Each of the three endpoints enumerates every asset it holds
        in one call, so there is no discovery gap for the hint to fill.
    """
    spot, earn, pocket = await asyncio.gather(
      self.spot_balances(),
      self.earn_balances(),
      self.pocket_balances(),
    )
    return SnapshotRecord(
      snapshot=Snapshot(
        subaccounts=[
          SubaccountSnapshot(subaccount='spot', balances=spot),
          SubaccountSnapshot(subaccount='earn', balances=earn),
          SubaccountSnapshot(subaccount='pocket', balances=pocket),
        ]
      ),
      provenance={'source': 'api', 'service': 'bit2me', 'id': source_id('bit2me')},
    )
