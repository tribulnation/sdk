from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.market.user import PerpPosition
from hyperliquid_sdk.perps.core import PerpMixin

@dataclass(frozen=True)
class Position(PerpMixin, PerpPosition):
  async def get(self) -> PerpPosition.Position:
    state = await self.client.info.clearinghouse_state(self.address)
    for entry in state['assetPositions']:
      pos = entry['position']
      if pos['coin'] == self.asset_name:
        return PerpPosition.Position(
          size=Decimal(pos['szi']),
          entry_price=Decimal(pos['entryPx']),
        )
    return PerpPosition.Position()
