from dataclasses import dataclass
from decimal import Decimal

from trading_sdk import LogicError
from trading_sdk.market.data import Index as _Index
from hyperliquid_sdk.perps.core import PerpMixin

@dataclass(frozen=True)
class Index(PerpMixin, _Index):
  async def price(self) -> Decimal:
    perp_meta, asset_ctxs = await self.client.info.perp_meta_and_asset_ctxs(self.dex)
    if perp_meta['universe'][self.asset_idx]['name'] != self.asset_meta['name']:
      raise LogicError(f'Expected asset {self.asset_meta["name"]} at index {self.asset_idx}, got {perp_meta["universe"][self.asset_idx]["name"]}')
    
    ctx = asset_ctxs[self.asset_idx]
    if self.index_price == 'oracle' or (mark := ctx.get('markPx')) is None:
      price = ctx['oraclePx']
    else:
      price = mark
    return Decimal(price)