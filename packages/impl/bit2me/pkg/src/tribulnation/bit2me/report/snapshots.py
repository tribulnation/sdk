from typing_extensions import AsyncContextManager, Collection, Iterable
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
from tribulnation.bit2me.core import wrap_exceptions

from typed_bit2me import Bit2Me


@dataclass(frozen=True)
class Snapshots(_Snapshots):
  client: Bit2Me

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    api_secret: str | None = None,
    *,
    validate: bool = True,
  ):
    return cls(
      client=Bit2Me.new(api_key=api_key, api_secret=api_secret, validate=validate)
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield from super().resources()
    yield self.client

  @SDK.method
  @wrap_exceptions
  async def spot_balances(self) -> Balances:
    out = Balances()
    balances = await self.client.v1.trading.balance()
    for entry in balances:
      if (asset := entry.get('currency')) is None:
        continue
      balance = Decimal(entry.get('balance', 0)) + Decimal(
        entry.get('blockedBalance', 0)
      )
      out[asset] += balance
    return out

  @SDK.method
  @wrap_exceptions
  async def earn_balances(self) -> Balances:
    out = Balances()
    wallets = await self.client.v2.earn.wallets()
    for entry in wallets.get('data', []):
      if (balance := entry.get('balance')) is not None and (
        currency := entry.get('currency')
      ) is not None:
        out[currency] += Decimal(balance)
    return out

  @SDK.method
  @wrap_exceptions
  async def pocket_balances(self) -> Balances:
    """Balances held in Bit2Me Wallet pockets.

    Wallet and Pro are separate products with separate balances -- funds move
    between them through `/v1/trading/wallet/{deposit,withdraw}` -- so pockets
    are not covered by `spot_balances`.
    """
    out = Balances()
    pockets = await self.client.v1.wallet.pockets.get()
    for entry in pockets:
      if (asset := entry.get('currency')) is None:
        continue
      out[asset] += Decimal(entry.get('balance', 0)) + Decimal(
        entry.get('blockedBalance', 0)
      )
    return out

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
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
