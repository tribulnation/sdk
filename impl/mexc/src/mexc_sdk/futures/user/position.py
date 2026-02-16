from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.market.user import PerpPosition as _PerpPosition

from mexc.futures.user_data.positions import PositionType
from mexc_sdk.core import MarketMixin, wrap_exceptions


def merge_positions(positions: list[_PerpPosition.Position]) -> _PerpPosition.Position:
  if not positions:
    return _PerpPosition.Position()

  total_size = sum(p.size for p in positions)
  if total_size == 0:
    return _PerpPosition.Position()

  entry_price = Decimal(sum(p.size * p.entry_price for p in positions)) / total_size
  return _PerpPosition.Position(size=Decimal(total_size), entry_price=entry_price)


@dataclass
class Position(MarketMixin, _PerpPosition):

  @wrap_exceptions
  async def get(self) -> _PerpPosition.Position:
    positions = await self.client.futures.positions(self.instrument)
    contract = await self.client.futures.contract_info(self.instrument)
    contract_size = Decimal(contract['contractSize'])

    out: list[_PerpPosition.Position] = []
    for pos in positions:
      s = 1 if pos['positionType'] == PositionType.long.value else -1
      size = s * abs(Decimal(pos['holdVol'])) * contract_size
      out.append(_PerpPosition.Position(size=size, entry_price=Decimal(pos['openAvgPrice'])))
    return merge_positions(out)