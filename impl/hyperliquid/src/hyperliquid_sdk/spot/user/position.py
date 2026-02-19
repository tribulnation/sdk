from dataclasses import dataclass
from decimal import Decimal

from trading_sdk import LogicError
from trading_sdk.market.user import Position as _Position
from hyperliquid_sdk.spot.core import SpotMixin

@dataclass(frozen=True)
class Position(SpotMixin, _Position):
  async def get(self) -> _Position.Position:
    state = await self.client.info.spot_clearinghouse_state(self.address)
    for balance in state['balances']:
      if balance['token'] == self.base_meta['index']:
        if balance['coin'] != self.base_meta['name']:
          raise LogicError(f'Found balance with matching index {balance["token"]}, but wrong coin "{balance["coin"]}" != "{self.quote_name}"')
        total = Decimal(balance['total'])
        return _Position.Position(total)
    return _Position.Position()
