from dataclasses import dataclass

from tribulnation.sdk.core import LogicError
from tribulnation.sdk.market.user_data.positions import (
  MyPosition as _MyPosition, Position
)

from dydx_sdk.core import MarketMixin, UserDataMixin, wrap_exceptions

@dataclass
class MyPosition(MarketMixin, UserDataMixin, _MyPosition):

  @wrap_exceptions
  async def position(self) -> Position | None:
    r = await self.indexer_data.list_positions(self.address, subaccount=self.subaccount, status='OPEN', unsafe=True)
    positions = [
      Position(
        side=p['side'],
        size=p['size'],
        entry_price=p['entryPrice'],
      )
      for p in r['positions']
        if p['market'] == self.market
    ]
    if len(positions) > 1:
      raise LogicError(f'Multiple positions found for {self.market}')
    elif len(positions) == 1:
      return positions[0]