from typing_extensions import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from collections import defaultdict
from decimal import Decimal
import asyncio

from trading_sdk.reporting import Snapshot, Snapshots as _Snapshots

from dydx_sdk.core import Mixin, wrap_exceptions

@dataclass(frozen=True)
class Snapshots(_Snapshots, Mixin):
  @wrap_exceptions
  async def snapshots(self, assets: Sequence[str] = []) -> Sequence[Snapshot]:
    time = datetime.now().astimezone()
    subaccounts = await self.indexer.data.get_subaccounts(self.address)
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
