from typing_extensions import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from collections import Counter
import asyncio

from sdk.reporting import (
  Snapshot, Snapshots as SnapshotsTDK,
)

from mexc_sdk.core import SdkMixin
from mexc_sdk.spot.user_data import Balances as SpotBalances
from mexc_sdk.futures.user_data import Balances as FuturesBalances, MyPosition

@dataclass
class Snapshots(SnapshotsTDK, SdkMixin):
  async def snapshots(self, assets: Sequence[str] = []) -> Sequence[Snapshot]:
    spot_r, future_r = await asyncio.gather(
      SpotBalances.balances(self), # type: ignore
      FuturesBalances.balances(self), # type: ignore
    )
    time = datetime.now(timezone.utc)
    spot_balances = { k: v.total for k, v in spot_r.items() }
    future_balances = { k: v.total for k, v in future_r.items() }
    balances: dict[str, Decimal] = Counter(spot_balances) + Counter(future_balances) # type: ignore

    currency_snapshots = [
      Snapshot(time=time, asset=currency, qty=balance, kind='currency')
      for currency, balance in balances.items()
    ]

    positions = await Positions.positions(self) # type: ignore
    time = datetime.now(timezone.utc)

    futures_snapshots = [
      Snapshot(time=time, asset=symbol, qty=p.size, avg_price=p.entry_price, kind='future')
      for symbol, p in positions.items()
    ]

    return currency_snapshots + futures_snapshots