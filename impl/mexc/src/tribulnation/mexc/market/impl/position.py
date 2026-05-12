from decimal import Decimal

from tribulnation.sdk.market import Position

from tribulnation.mexc.core.exc import wrap_exceptions
from .mixin import MarketMixin


@wrap_exceptions
async def position(self: MarketMixin) -> Position:
  r = await self.client.spot.account.info(recvWindow=self.shared.recvWindow, validate=self.shared.validate)
  for b in r["balances"]:
    if b["asset"] == self.info["baseAsset"]:
      total = Decimal(b["free"]) + Decimal(b["locked"])
      return Position(size=total)
  return Position()
