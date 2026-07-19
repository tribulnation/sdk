from typing_extensions import Collection
from dataclasses import dataclass
from decimal import Decimal
from collections import defaultdict
import asyncio

from tribulnation.sdk import SDK
from tribulnation.sdk.reporting import (
  Balances, Snapshot, SnapshotResult, SubaccountSnapshot, Snapshots as _Snapshots,
  source_id, Position,
)

from tribulnation.mexc.core import Mixin, wrap_exceptions

@dataclass(frozen=True)
class Snapshots(_Snapshots, Mixin):
  @SDK.method
  @wrap_exceptions
  async def spot_balances(self) -> Balances:
    r = await self.client.spot.account.info(recv_window=self.recvWindow)
    return Balances({
      b.get('asset') or '': Decimal(b.get('free') or '0') + Decimal(b.get('locked') or '0')
      for b in r.get('balances', [])
    })

  @SDK.method
  @wrap_exceptions
  async def futures_balances(self) -> Balances:
    r = await self.client.futures.account.assets()
    data = r.get('data')
    if data is None:
      raise ValueError('MEXC futures assets response did not include data')
    return Balances({
      b.get('currency') or '': Decimal(str(b.get('availableBalance') or '0')) + Decimal(str(b.get('positionMargin') or '0'))
      for b in data
    })

  @SDK.method
  @wrap_exceptions
  async def futures_positions(self):
    response = await self.client.futures.position.open()
    data = response.get('data')
    if data is None:
      raise ValueError('MEXC futures positions response did not include data')
    out = defaultdict[str, list[Position]](list)

    for pos in data:
      symbol = pos.get('symbol')
      if symbol is None:
        continue
      contract_response = await self.client.futures.market.contract_info(symbol=symbol)
      contract = contract_response.get('data')
      if contract is None:
        raise ValueError(f'MEXC contract info response did not include data for {symbol}')
      if isinstance(contract, list):
        contract = next(c for c in contract if c.get('symbol') == symbol)
      contract_size = Decimal(str(contract.get('contractSize') or '0'))
      s = 1 if pos.get('positionType') == 1 else -1
      size = s * abs(Decimal(str(pos.get('holdVol') or '0'))) * contract_size
      out[symbol].append(Position(size=size, avg_price=Decimal(str(pos.get('openAvgPrice') or '0'))))

    return { symbol: Position.merge(positions) for symbol, positions in out.items() }
  
  @SDK.method
  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotResult:
    spot_balances, future_balances, future_positions = await asyncio.gather(
      self.spot_balances(),
      self.futures_balances(),
      self.futures_positions(),
    )
    return SnapshotResult(
      snapshot=Snapshot(subaccounts=[
        SubaccountSnapshot(subaccount='spot', balances=spot_balances),
        SubaccountSnapshot(
          subaccount='futures',
          balances=future_balances,
          positions=future_positions,
        ),
      ]),
      provenance={'source': 'api', 'service': 'mexc', 'id': source_id('mexc')},
    )
