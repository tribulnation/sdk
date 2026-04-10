from typing_extensions import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
from decimal import Decimal

from dydx_sdk.core import wrap_exceptions
from trading_sdk.reporting import Snapshot, Snapshots as _Snapshots

from dydx import Indexer

@dataclass(frozen=True)
class Snapshots(_Snapshots):
  address: str
  indexer: Indexer = field(default_factory=Indexer.new)

  @classmethod
  def new(cls, address: str | None = None):
    if address is None:
      import os
      address = os.environ['DYDX_ADDRESS']
    return cls(address=address)

  async def __aenter__(self):
    await self.indexer.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.indexer.__aexit__(exc_type, exc_value, traceback)

  @wrap_exceptions
  async def snapshots(self, assets: Sequence[str] = []) -> Sequence[Snapshot]:
    time = datetime.now().astimezone()
    subaccounts = (await self.indexer.data.get_subaccounts(self.address))['subaccounts']
    equity = Decimal(0)
    unrealized = Decimal(0)
    realized = Decimal(0)

    positions = defaultdict[str, Decimal](Decimal)
    total_prices = defaultdict[str, Decimal](Decimal)

    for sub in subaccounts:
      equity += Decimal(sub['equity'])

      for position in sub['openPerpetualPositions'].values():
        if (pnl := position.get('realizedPnl')) is not None:
          realized += Decimal(pnl)
        if (pnl := position.get('unrealizedPnl')) is not None:
          unrealized += Decimal(pnl)

        positions[position['market']] += position['size']
        total_prices[position['market']] += position['size'] * position['entryPrice']

    collateral = equity - unrealized
    entry_prices = {
      market: total_prices[market] / positions[market]
      for market in positions
    }

    return [
      Snapshot(asset='USDC', time=time, qty=collateral, kind='currency')
    ] + [
      Snapshot(asset=market, time=time, qty=positions[market], avg_price=entry_prices[market], kind='future')
      for market in positions
    ]
