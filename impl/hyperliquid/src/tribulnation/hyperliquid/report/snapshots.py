from typing_extensions import Collection
from dataclasses import dataclass
from collections import defaultdict, Counter
from datetime import datetime
from decimal import Decimal
import asyncio

from tribulnation.sdk import SDK
from tribulnation.sdk.reporting import Balance, Record, Snapshots as _Snapshots, Snapshot
from hyperliquid.info import Info
from tribulnation.hyperliquid.core import wrap_exceptions

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
  async def spot_balances(self):
    spot = await self.info.spot_clearinghouse_state(self.address)
    return {
      str(balance['token']): qty
      for balance in spot['balances']
        if (qty := Decimal(balance['total'])) > 0
    }

  @SDK.method
  @wrap_exceptions
  async def dex_meta(self, dex: str):
    meta, _ = await self.info.perp_meta_and_asset_ctxs(dex)
    return meta

  @SDK.method
  @wrap_exceptions
  async def clearinghouse_state(self, dex: str):
    return await self.info.clearinghouse_state(self.address, dex=dex)

  async def dex_positions_and_pnl(self, dex: str | None):
    dex = dex or ''
    state, meta = await asyncio.gather(
      self.clearinghouse_state(dex),
      self.dex_meta(dex),
    )
    balances = {
      p['position']['coin']: Balance(
        qty=Decimal(p['position']['szi']), avg_price=Decimal(p['position']['entryPx']), kind='future'
      )
      for p in state['assetPositions']
    }
    unrealized = sum(Decimal(p['position']['unrealizedPnl']) for p in state['assetPositions'])
    return balances, {str(meta['collateralToken']): Decimal(unrealized)}


  @SDK.method
  @wrap_exceptions
  async def perp_snapshots_and_pnl(self):
    dexs = await self.info.perp_dexs()
    results = await asyncio.gather(*[
      self.dex_positions_and_pnl(dex and dex['name'])
      for dex in dexs
    ])
    positions: dict[str, Balance] = {}
    pnls = Counter()
    for balances, pnl in results:
      positions.update(balances)
      pnls.update(pnl)
    return positions, pnls

  async def snapshots(self, assets: Collection[str] | None = None) -> Record:
    stake, spot_balances, (perp_snapshots, perp_pnls) = await asyncio.gather(
      self.stake_snapshot(),
      self.spot_balances(),
      self.perp_snapshots_and_pnl(),
    )
    time = datetime.now().astimezone()
    balances = defaultdict(Decimal, spot_balances)
    for asset, pnl in perp_pnls.items():
      balances[asset] -= pnl
    if stake > 0:
      balances[HYPE_ASSET] += stake

    snapshots = perp_snapshots | {
      asset: Balance(qty=qty, kind='currency')
      for asset, qty in balances.items()
    }
    return Record(
      snapshots=[Snapshot(time=time, balances=snapshots)],
      provenance={'source': 'api', 'service': 'hyperliquid', 'id': time.isoformat()},
    )
