from dataclasses import dataclass as _dataclass, field as _field

from dydx_sdk.core import Mixin, MarketMixin, Settings
from dydx.indexer.types import PerpetualMarket as _PerpetualMarket
from .market import Market

@_dataclass
class Cache:
  markets: dict[str, _PerpetualMarket] = _field(default_factory=dict)

@_dataclass(kw_only=True, frozen=True)
class DYDX(Mixin):
  cache: Cache = _field(default_factory=Cache)

  async def cached_market(self, market: str, *, refetch: bool = False) -> _PerpetualMarket:
    if refetch or market not in self.cache.markets:
      self.cache.markets[market] = await self.indexer.data.get_market(market)
    return self.cache.markets[market]

  async def market(
    self, market: str, *, subaccount: int = 0,
    settings: Settings = {}, refetch: bool = False
  ) -> Market:
    perp_market = await self.cached_market(market, refetch=refetch)
    mixin = MarketMixin(
      perpetual_market=perp_market, address=self.address, subaccount=subaccount,
      indexer=self.indexer, public_node=self.public_node, private_node=self.private_node,
      streams=self.streams, settings=settings,
    )
    return Market.of(mixin)