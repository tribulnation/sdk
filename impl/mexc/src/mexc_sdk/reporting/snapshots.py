from typing_extensions import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from collections import Counter, defaultdict
import asyncio

from trading_sdk import SDK
from trading_sdk.reporting import (
  Snapshot, Snapshots as _Snapshots
)

from mexc_sdk.core import Mixin, wrap_exceptions
from mexc.futures.user_data.positions import PositionType

@dataclass
class Position:
  size: Decimal
  entry_price: Decimal

def merge_positions(positions: list[Position]) -> Position:
  size = sum(p.size for p in positions)
  if size == 0:
    return Position(size=Decimal(0), entry_price=Decimal(0))
  entry_price = sum(p.size * p.entry_price for p in positions) / size
  return Position(size=size, entry_price=entry_price)

@dataclass(frozen=True)
class Snapshots(_Snapshots, Mixin):
  @SDK.method
  @wrap_exceptions
  async def spot_balances(self):
    r = await self.client.spot.account(recvWindow=self.recvWindow)
    return {
      b['asset']: Decimal(b['free']) + Decimal(b['locked'])
      for b in r['balances']
    }

  @SDK.method
  @wrap_exceptions
  async def futures_balances(self):
    r = await self.client.futures.assets(recvWindow=self.recvWindow)
    return {
      b['currency']: Decimal(b['availableBalance']) + Decimal(b['positionMargin'])
      for b in r
    }

  @SDK.method
  @wrap_exceptions
  async def futures_positions(self):
    positions = await self.client.futures.positions()
    out = defaultdict[str, list[Position]](list)

    for pos in positions:
      contract = await self.client.futures.contract_info(pos['symbol'])
      contract_size = Decimal(contract['contractSize'])
      s = 1 if pos['positionType'] == PositionType.long.value else -1
      size = s * abs(Decimal(pos['holdVol'])) * contract_size
      out[pos['symbol']].append(Position(size=size, entry_price=Decimal(pos['openAvgPrice'])))

    return { symbol: merge_positions(positions) for symbol, positions in out.items() }
  
  @SDK.method
  async def snapshots(self, assets: Sequence[str] = []) -> Sequence[Snapshot]:
    spot_balances, future_balances, future_positions = await asyncio.gather(
      self.spot_balances(),
      self.futures_balances(),
      self.futures_positions(),
    )
    time = datetime.now(timezone.utc)
    balances: dict[str, Decimal] = Counter(spot_balances) + Counter(future_balances) # type: ignore

    currency_snapshots = [
      Snapshot(time=time, asset=currency, qty=balance, kind='currency')
      for currency, balance in balances.items()
    ]

    futures_snapshots = [
      Snapshot(time=time, asset=symbol, qty=p.size, avg_price=p.entry_price, kind='future')
      for symbol, p in future_positions.items()
    ]

    return currency_snapshots + futures_snapshots