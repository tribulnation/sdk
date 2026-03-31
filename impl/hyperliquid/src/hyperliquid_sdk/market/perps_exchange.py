from typing_extensions import Sequence
from dataclasses import dataclass

from trading_sdk.market import PerpExchange as _PerpExchange

from .impl import PerpMixin
from .perps_market import PerpMarket


@dataclass(frozen=True, kw_only=True)
class PerpExchange(PerpMixin, _PerpExchange):

  @property
  def venue_id(self) -> str:
    return 'hyperliquid'

  @property
  def exchange_id(self) -> str:
    return self.dex_name or ''

  async def markets(self) -> Sequence[str]:
    # Use default/no-dex universe here; callers that care about DEX can pass it when constructing.
    _, perp_meta, _ctxs = await self.shared.load_perp_meta_for_dex(self.dex_name)
    return [asset["name"] for asset in perp_meta["universe"]]

  async def market(self, market_id: str, /):
    meta = await self.shared.perp_meta_of(market_id, dex_name=self.dex_name)
    return PerpMarket(shared=self.shared, dex=self.dex, meta=meta)

