import os
from dataclasses import dataclass as _dataclass

from dydx_sdk.core import Mixin, MarketMixin, Settings

from .market import Market

@_dataclass(kw_only=True, frozen=True)
class DYDX(Mixin):

  async def market(self, market: str, *, subaccount: int = 0, settings: Settings = {}) -> Market:
    perp_market = await self.indexer.data.get_market(market)
    mixin = MarketMixin(
      perpetual_market=perp_market, address=self.address, subaccount=subaccount,
      indexer=self.indexer, public_node=self.public_node, private_node=self.private_node,
      streams=self.streams, settings=settings,
    )
    return Market.of(mixin)