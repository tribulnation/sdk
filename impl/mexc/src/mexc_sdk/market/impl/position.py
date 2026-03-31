from decimal import Decimal

from trading_sdk.market import Position

from mexc_sdk.core.exc import wrap_exceptions
from .mixin import MarketMixin


@wrap_exceptions
async def position(self: MarketMixin) -> Position:
  r = await self.client.spot.account(recvWindow=self.shared.recvWindow, validate=self.shared.validate)
  for b in r["balances"]:
    if b["asset"] == self.info["baseAsset"]:
      total = Decimal(b["free"]) + Decimal(b["locked"])
      return Position(size=total)
  return Position()

