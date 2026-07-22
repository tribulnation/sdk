from typing_extensions import Collection, Mapping, Sequence
from dataclasses import dataclass

from tribulnation.sdk.market import PerpExchange as _PerpExchange, PerpCollateral, PerpStats, Settings, Ticker

from .impl import PerpMixin, perp_exchange_collateral, perp_stats, perp_tickers
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

  async def perp_stats(
    self, markets: Collection[str] | None = None, *, settings: Settings = {},
  ) -> Mapping[str, PerpStats]:
    """Fetch pricing and funding stats for the whole perp universe in one call.

    Args:
      markets: Asset names to keep. `None` keeps the whole universe.
      settings: Venue settings; `hyperliquid.index_price` selects oracle vs mark.

    Returns:
      A mapping of asset name to its `PerpStats`.
    """
    return await perp_stats(self, markets, settings=settings)

  async def tickers(
    self, markets: Collection[str] | None = None, *, settings: Settings = {},
  ) -> Mapping[str, Ticker]:
    return await perp_tickers(self, markets, settings=settings)

  async def markets(self) -> Sequence[str]:
    # Use default/no-dex universe here; callers that care about DEX can pass it when constructing.
    _, perp_meta, _ctxs = await self.shared.load_perp_meta_for_dex(self.dex_name)
    return [asset["name"] for asset in perp_meta["universe"]]

  async def market(self, market_id: str, /):
    meta = await self.shared.perp_meta_of(market_id, dex_name=self.dex_name)
    return PerpMarket(shared=self.shared, dex=self.dex, meta=meta)
