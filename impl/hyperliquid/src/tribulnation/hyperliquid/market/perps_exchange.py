from typing_extensions import Sequence
from dataclasses import dataclass

from tribulnation.sdk.market import PerpExchange as _PerpExchange, PerpCollateral

from .impl import PerpMixin, perp_exchange_collateral
from .perps_market import PerpMarket


@dataclass(frozen=True, kw_only=True)
class PerpExchange(PerpMixin, _PerpExchange):

  @property
  def venue_id(self) -> str:
    return 'hyperliquid'

  @property
  def exchange_id(self) -> str:
    return self.dex_name or ''

  async def perp_collateral(self, market_id: str | None = None, /) -> PerpCollateral:
    if market_id is not None:
      m = await self.market(market_id)
      return await m.perp_collateral()
    return await perp_exchange_collateral(self)

  async def markets(self) -> Sequence[str]:
    # Use default/no-dex universe here; callers that care about DEX can pass it when constructing.
    _, perp_meta, _ctxs = await self.shared.load_perp_meta_for_dex(self.dex_name)
    return [asset["name"] for asset in perp_meta["universe"]]

  async def market(self, market_id: str, /):
    meta = await self.shared.perp_meta_of(market_id, dex_name=self.dex_name)
    return PerpMarket(shared=self.shared, dex=self.dex, meta=meta)

