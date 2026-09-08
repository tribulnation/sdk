"""Kraken implementation of the `snapshot` reporting endpoint, over `Balance`."""

from typing_extensions import Collection
from dataclasses import dataclass

from tribulnation.sdk.reporting import (
  Snapshot,
  SnapshotRecord,
  Snapshots as _Snapshots,
  SubaccountSnapshot,
  source_id,
)
from tribulnation.kraken.core import Mixin


@dataclass(frozen=True, kw_only=True)
class Snapshots(_Snapshots, Mixin):
  """Kraken implementation of `Snapshots`.

  `Balance` lists every asset the account holds in one call, keyed by internal
  asset id. Funds in Earn appear under suffixed ids of their own (`XXBT.F` for
  Kraken Rewards, `.B` for bonded products), which are reported as the venue names
  them. Spot has no positions, so none are reported.
  """

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    """Fetch the account's balances.

    Args:
      assets: Ignored. `Balance` enumerates every held asset in one call, so there
        is no discovery gap for the hint to fill.
    """
    balances = await self.call_kraken(self.client.spot.account.balance)
    return SnapshotRecord(
      snapshot=Snapshot(subaccounts=[SubaccountSnapshot(balances=dict(balances))]),
      provenance={'source': 'api', 'service': 'kraken', 'id': source_id('kraken')},
    )
