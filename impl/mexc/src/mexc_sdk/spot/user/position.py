from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.market.user import Position as _Position

from mexc_sdk.core import SpotMixin, wrap_exceptions

@dataclass
class Position(SpotMixin, _Position):
  @wrap_exceptions
  async def get(self) -> _Position.Position:
    r = await self.client.spot.account(recvWindow=self.recvWindow)
    for b in r['balances']:
      if b['asset'] == self.info['baseAsset']:
        total = Decimal(b['free']) + Decimal(b['locked'])
        return _Position.Position(total)
    return _Position.Position()