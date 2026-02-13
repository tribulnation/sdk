from dataclasses import dataclass

from tribulnation.sdk.core import LogicError
from tribulnation.sdk.market.user_data.my_position import (
  MyPosition as _MyPosition, Position
)

from dydx_sdk.core import MarketMixin, UserDataMixin, wrap_exceptions

@dataclass
class MyPosition(MarketMixin, UserDataMixin, _MyPosition):

  @wrap_exceptions
  async def position(self) -> Position | None:
    r = await self.indexer_data.list_positions(self.address, subaccount=self.subaccount, status='OPEN', unsafe=True)
    for p in r['positions']:
      if p['size'] < 0 and p['side'] == 'LONG':
        raise LogicError(f'Found long position with negative size: {p}')
      elif p['size'] > 0 and p['side'] == 'SHORT':
        raise LogicError(f'Found short position with positive size: {p}')
        
    positions = [
      Position(
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