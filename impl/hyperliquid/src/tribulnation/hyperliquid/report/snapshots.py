from typing_extensions import Collection
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import asyncio

from tribulnation.sdk.reporting import Balance, Record, Snapshots as _Snapshots, Snapshot
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

  async def spot_balances(self):
    spot = await self.info.spot_clearinghouse_state(self.address)
    return {
      str(balance['token']): Balance(qty=qty, kind='currency')
      for balance in spot['balances']
        if (qty := Decimal(balance['total'])) > 0
    }

  async def dex_balances(self, dex: str | None):
    dex = dex or ''
    state = await self.info.clearinghouse_state(self.address, dex=dex)
    return {
      p['position']['coin']: Balance(
        qty=Decimal(p['position']['szi']), avg_price=Decimal(p['position']['entryPx']), kind='future'
      )
      for p in state['assetPositions']
    }

  async def perp_balances(self):
    dexs = await self.info.perp_dexs()
    nested_balances = await asyncio.gather(*[
      self.dex_balances(dex and dex['name'])
      for dex in dexs
    ])
    return {
      asset: balance
      for balances in nested_balances
      for asset, balance in balances.items()
    }

  async def snapshots(self, assets: Collection[str] | None = None) -> Record:
    stake, spot_balances, perp_balances = await asyncio.gather(
      self.stake_snapshot(),
      self.spot_balances(),
      self.perp_balances(),
    )
    time = datetime.now().astimezone()
    balances = spot_balances | perp_balances
    if stake > 0:
      hype_qty = stake
      if (hype_balance := balances.get(HYPE_ASSET)) is not None:
        hype_qty += hype_balance.qty
      balances[HYPE_ASSET] = Balance(qty=hype_qty, kind='currency')
    return Record(
      snapshots=[Snapshot(time=time, balances=balances)],
      provenance={'source': 'api', 'service': 'hyperliquid', 'endpoint': 'snapshots'},
    )
