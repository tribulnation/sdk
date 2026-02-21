import os
from dataclasses import dataclass as _dataclass, field as _field

from dydx.indexer import Indexer as _Indexer
from dydx.node import PrivateNode as _PrivateNode
from dydx_sdk.core import TradingSettings as _TradingSettings

from .market import Market

@_dataclass(kw_only=True)
class DYDX:
  address: str
  indexer: _Indexer = _field(default_factory=_Indexer.new)
  node: _PrivateNode

  @classmethod
  async def connect(
    cls, *, mnemonic: str | None = None, validate: bool = True
  ):
    indexer = _Indexer.new(validate=validate)
    node = await _PrivateNode.connect(mnemonic)
    return cls(address=node.address, indexer=indexer, node=node)

  async def market(self, market: str, *, subaccount: int = 0, settings: _TradingSettings = {}) -> Market:
    perp_market = await self.indexer.data.get_market(market)
    return Market.new(
      market, address=self.address, subaccount=subaccount,
      indexer=self.indexer, node=self.node,
      perpetual_market=perp_market, settings=settings,
    )