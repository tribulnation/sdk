from typing_extensions import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import asyncio

from trading_sdk.reporting import Snapshots as _Snapshots, Snapshot
from hyperliquid import Info

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

  async def stake_snapshot(self):
    summary = await self.info.staking_summary(self.address)
    return Decimal(summary['delegated']) + Decimal(summary['undelegated'])

  async def spot_snapshots(self):
    spot = await self.info.spot_clearinghouse_state(self.address)
    time = datetime.now().astimezone()
    return [
      Snapshot(asset=str(balance['token']), time=time, qty=qty, kind='currency')
      for balance in spot['balances']
        if (qty := Decimal(balance['total'])) > 0
    ]

  async def dex_snapshots(self, dex: str | None):
    dex = dex or ''
    state = await self.info.clearinghouse_state(self.address, dex=dex)
    time = datetime.now().astimezone()
    return [
      Snapshot(
        asset=p['position']['coin'], time=time,
        qty=Decimal(p['position']['szi']),
        avg_price=Decimal(p['position']['entryPx']),
        kind='future'
      )
      for p in state['assetPositions']
    ]

  async def perp_snapshots(self):
    dexs = await self.info.perp_dexs()
    nested_snapshots = await asyncio.gather(*[
      self.dex_snapshots(dex and dex['name'])
      for dex in dexs
    ])
    return [s for ss in nested_snapshots for s in ss]

  async def snapshots(self, assets: Sequence[str] = []) -> list[Snapshot]:
    stake, spot_snaps, perp_snaps = await asyncio.gather(
      self.stake_snapshot(),
      self.spot_snapshots(),
      self.perp_snapshots(),
    )
    time = datetime.now().astimezone()
    out = spot_snaps + perp_snaps
    if stake > 0:
      hype_snap = Snapshot(asset=HYPE_ASSET, time=time, qty=stake, kind='currency')
      for snap in list(spot_snaps):
        if snap.asset == HYPE_ASSET:
          hype_snap.qty += snap.qty
          spot_snaps.remove(snap)
      out.append(hype_snap)
    return out