"""Balance and position snapshots for one Coinbase account."""

from typing_extensions import Collection
from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import (
  Balances,
  Position,
  Snapshot,
  SnapshotRecord,
  Snapshots as _Snapshots,
  SubaccountSnapshot,
  source_id,
)

from tribulnation.coinbase.core import Mixin, wrap_exceptions

SERVICE = 'coinbase'


@dataclass(frozen=True, kw_only=True)
class Snapshots(Mixin, _Snapshots):
  """Snapshots for one Coinbase account.

  Balances live in two parallel places -- v2 wallets/vaults/fiat accounts, and the v3
  brokerage accounts backing Advanced Trade -- and the same asset is reported by both,
  so they are kept as separate subaccounts rather than summed.
  """

  @SDK.method
  async def wallet_balances(self, assets: Collection[str] | None = None) -> Balances:
    """Sum the v2 wallet, vault and fiat account balances, per asset."""
    out = Balances()
    for account in await self.app.accounts.list_paged().via(self.call_app):
      asset = account['balance']['currency']
      if assets is None or asset in assets:
        out[asset] += account['balance']['amount']
    return out

  @SDK.method
  async def brokerage_balances(self, assets: Collection[str] | None = None) -> Balances:
    """Sum the v3 Advanced Trade brokerage account balances, per asset."""
    paging = self.app.advanced_trade.http.accounts.list_paged()
    out = Balances()
    for account in await paging.via(self.call_app):
      asset = account['currency']
      if assets is None or asset in assets:
        out[asset] += account['available_balance']['value']
    return out

  @SDK.method
  @wrap_exceptions
  async def futures_positions(self) -> dict[str, Position]:
    """Fetch the CFM dated-futures positions.

    INTX perpetual positions are deliberately absent: reaching them needs a key scoped
    to an INTX portfolio, and a retail key gets `PERMISSION_DENIED` rather than an
    empty book, so including them would turn every snapshot on a retail key into an
    error. Read them from `PerpMarket.perp_position` on a key that has the scope.
    """
    response = await self.app.advanced_trade.http.futures.positions.list()
    return {
      position['product_id']: Position(
        size=Decimal(position['number_of_contracts']),
        avg_price=position['avg_entry_price'],
      )
      for position in response['positions']
    }

  @SDK.method
  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    """Fetch the account's current balances and positions."""
    return SnapshotRecord(
      snapshot=Snapshot(
        subaccounts=[
          SubaccountSnapshot(
            subaccount='accounts', balances=await self.wallet_balances(assets)
          ),
          SubaccountSnapshot(
            subaccount='advanced_trade',
            balances=await self.brokerage_balances(assets),
          ),
          SubaccountSnapshot(
            subaccount='futures', positions=await self.futures_positions()
          ),
        ]
      ),
      provenance={'source': 'api', 'service': SERVICE, 'id': source_id(SERVICE)},
    )
