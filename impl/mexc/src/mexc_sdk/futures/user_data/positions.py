from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market.user_data.my_position import MyPosition as _MyPosition, Position

from mexc_sdk.core import MarketMixin, wrap_exceptions
from mexc.futures.user_data.positions import PositionType

def merge_positions(positions: list[Position]) -> Position | None:
  if positions:
    total_size = sum(p.size for p in positions)
    return Position(
      size=Decimal(sum(p.size for p in positions)),
      entry_price=Decimal(sum(p.size * p.entry_price for p in positions)) / total_size,
    )

@dataclass
class MyPosition(MarketMixin, _MyPosition):
  @wrap_exceptions
  async def position(self) -> Position | None:
    r = await self.client.futures.positions(self.instrument)
    contract = await self.client.futures.contract_info(self.instrument)
    contract_size = contract['contractSize']
    positions: list[Position] = []

    for p in r:
      s = 1 if p['positionType'] == PositionType.long.value else -1
      size = s * abs(p['holdVol']) * contract_size
      positions.append(Position(size=size, entry_price=p['openAvgPrice']))

    return merge_positions(positions)