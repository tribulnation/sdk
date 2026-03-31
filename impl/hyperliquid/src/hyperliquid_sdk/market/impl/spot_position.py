from decimal import Decimal

from trading_sdk.market import Position

from hyperliquid_sdk.core import wrap_exceptions
from .mixin import SpotMarketMixin


@wrap_exceptions
async def position(self: SpotMarketMixin) -> Position:
  state = await self.client.info.spot_clearinghouse_state(self.address)
  for balance in state["balances"]:
    if balance["token"] == self.meta["base_meta"]["index"]:
      total = Decimal(balance["total"])
      return Position(size=total)
  return Position()

