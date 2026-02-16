from dataclasses import dataclass as _dataclass

from dydx.indexer import IndexerData as _IndexerData
from dydx.node import PublicNode as _PublicNode

from trading_sdk.market import PerpMarketData
from .depth import Depth
from .funding import Funding
from .index import Index
from .rules import Rules

@_dataclass(frozen=True)
class MarketData(PerpMarketData):
  depth: Depth
  funding: Funding
  index: Index
  rules: Rules

  @classmethod
  def new(
    cls, market: str, *,
    address: str,
    indexer_data: _IndexerData,
    public_node: _PublicNode,
  ):
    return cls(
      depth=Depth(market=market, indexer_data=indexer_data),
      funding=Funding(market=market, indexer_data=indexer_data),
      index=Index(market=market, indexer_data=indexer_data),
      rules=Rules(market=market, public_node=public_node, address=address)
    )
