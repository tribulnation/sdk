from dataclasses import dataclass
from decimal import Decimal

from trading_sdk import LogicError
from trading_sdk.market.user import Balances as _Balances
from hyperliquid_sdk.spot.core import SpotMixin

@dataclass(frozen=True)
class Balances(SpotMixin, _Balances):
  async def quote(self) -> _Balances.Balance:
    state = await self.client.info.spot_clearinghouse_state(self.address)
    for balance in state['balances']:
      if balance['token'] == self.quote_meta['index']:
        if balance['coin'] != self.quote_meta['name']:
          raise LogicError(f'Found balance with matching index {balance["token"]}, but wrong coin "{balance["coin"]}" != "{self.quote_name}"')
        total = Decimal(balance['total'])
        locked = Decimal(balance['hold'])
        return _Balances.Balance(
          free=total - locked,
          locked=locked
        )
    return _Balances.Balance()
