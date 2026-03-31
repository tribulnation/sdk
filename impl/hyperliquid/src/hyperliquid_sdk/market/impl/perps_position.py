from decimal import Decimal

from trading_sdk.market import PerpPosition

from hyperliquid_sdk.core import wrap_exceptions
from .mixin import PerpMarketMixin


@wrap_exceptions
async def position(self: PerpMarketMixin) -> PerpPosition:
  state = await self.client.info.clearinghouse_state(self.address, dex=self.dex_name)
  for entry in state["assetPositions"]:
    pos = entry["position"]
    if pos["coin"] == self.asset_name:
      return PerpPosition(size=Decimal(pos["szi"]), entry_price=Decimal(pos["entryPx"]))
  return PerpPosition()

