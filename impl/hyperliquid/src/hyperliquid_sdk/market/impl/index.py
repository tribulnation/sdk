from decimal import Decimal

from hyperliquid_sdk.core import wrap_exceptions
from .mixin import PerpMarketMixin


@wrap_exceptions
async def index(self: PerpMarketMixin) -> Decimal:
  perp_meta, asset_ctxs = await self.shared.load_perp_meta()
  if perp_meta["universe"][self.asset_idx]["name"] != self.asset_name:
    raise ValueError(
      f"Expected asset {self.asset_name} at index {self.asset_idx}, got {perp_meta['universe'][self.asset_idx]['name']}"
    )

  ctx = asset_ctxs[self.asset_idx]
  if self.index_price == "oracle" or (mark := ctx.get("markPx")) is None:
    return Decimal(ctx["oraclePx"])
  return Decimal(mark)

