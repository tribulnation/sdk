from typing_extensions import Collection
from dataclasses import dataclass
from decimal import Decimal
import asyncio

from tribulnation.sdk import SDK
from tribulnation.sdk.reporting import (
  Balances, Position, Snapshot, SnapshotRecord, Snapshots as _Snapshots,
  SubaccountSnapshot,
)
from hyperliquid.info import Info
from tribulnation.hyperliquid.core import wrap_exceptions

from .subaccounts import STAKING, UNIFIED

HYPE_ASSET = '150'

@dataclass
class Snapshots(_Snapshots):
  info: Info
  address: str

  @classmethod
  def http(cls, address: str, *, validate: bool = True, mainnet: bool = True):
    info = Info.http(validate=validate, mainnet=mainnet)
    return cls(info, address)
  
  @classmethod
  def ws(cls, address: str, *, validate: bool = True, mainnet: bool = True):
    info = Info.ws(validate=validate, mainnet=mainnet)
    return cls(info, address)

  @SDK.method
  @wrap_exceptions
  async def stake_snapshot(self):
    summary = await self.info.staking_summary(self.address)
    return Decimal(summary['delegated']) + Decimal(summary['undelegated'])

  @SDK.method
  @wrap_exceptions
  async def spot_balances(self) -> Balances:
    spot = await self.info.spot_clearinghouse_state(self.address)
    return Balances({
      str(balance['token']): qty
      for balance in spot['balances']
        if (qty := Decimal(balance['total'])) > 0
    })

  @SDK.method
  @wrap_exceptions
  async def dex_meta(self, dex: str):
    meta, _ = await self.info.perp_meta_and_asset_ctxs(dex)
    return meta

  @SDK.method
  @wrap_exceptions
  async def clearinghouse_state(self, dex: str):
    return await self.info.clearinghouse_state(self.address, dex=dex)

  async def dex_positions_and_pnl(
    self, dex: str | None,
  ) -> tuple[dict[str, Position], Balances]:
    """Positions on one dex, and the unrealized PnL its spot balance carries.

    On a unified account the spot balance of a collateral token is the whole
    perp equity backing that token — **cross and isolated alike**, unrealized
    PnL included. So every position's `unrealizedPnl` is subtracted to leave
    collateral, and `leverage.rawUsd` is not added: isolated margin is an
    allocation out of that same balance, not a bucket beside it.

    Verified against a live account carrying an isolated position: over 2.5
    minutes of price movement, `spot - sum(unrealizedPnl)` held at
    `9027.73703382` while unrealized PnL moved by ~21, and dropping the isolated
    leg from the sum made the result drift by exactly that leg's change.
    """
    dex = dex or ''
    state, meta = await asyncio.gather(
      self.clearinghouse_state(dex),
      self.dex_meta(dex),
    )
    positions = {
      p['position']['coin']: Position(
        size=Decimal(p['position']['szi']),
        avg_price=Decimal(p['position']['entryPx']),
      )
      for p in state['assetPositions']
    }
    unrealized = sum(
      (Decimal(p['position']['unrealizedPnl']) for p in state['assetPositions']),
      start=Decimal(0),
    )
    return positions, Balances({str(meta['collateralToken']): unrealized})

  @SDK.method
  @wrap_exceptions
  async def perp_positions_and_pnl(self) -> tuple[dict[str, Position], Balances]:
    """Positions across every dex, and the unrealized PnL per collateral token."""
    dexs = await self.info.perp_dexs()
    results = await asyncio.gather(*[
      self.dex_positions_and_pnl(dex and dex['name'])
      for dex in dexs
    ])
    positions: dict[str, Position] = {}
    pnls = Balances()
    for pos, pnl in results:
      positions.update(pos)
      pnls += pnl
    return positions, pnls

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    stake, spot_balances, (perp_positions, perp_pnls) = await asyncio.gather(
      self.stake_snapshot(),
      self.spot_balances(),
      self.perp_positions_and_pnl(),
    )
    balances = Balances(spot_balances)
    for asset, pnl in perp_pnls.items():
      balances[asset] -= pnl
    staking = {HYPE_ASSET: stake} if stake > 0 else {}
    snapshot = Snapshot(subaccounts=[
        SubaccountSnapshot(
          subaccount=UNIFIED, balances=balances, positions=perp_positions,
        ),
        SubaccountSnapshot(subaccount=STAKING, balances=staking),
      ])
    return SnapshotRecord(
      snapshot=snapshot,
      provenance={'source': 'api', 'service': 'hyperliquid', 'id': snapshot.time.isoformat()},
    )
