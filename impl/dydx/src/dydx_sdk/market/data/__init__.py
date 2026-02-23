from dataclasses import dataclass as _dataclass

from trading_sdk.market import PerpMarketData
from dydx_sdk.core import MarketMixin
from .depth import Depth
from .funding import Funding
from .index import Index
from .rules import Rules

@_dataclass(frozen=True)
class MarketData(MarketMixin, PerpMarketData):
  rules: Rules
  depth: Depth
  funding: Funding
  index: Index

  @classmethod
  def of(cls, other: MarketMixin):
    return cls(
      address=other.address,
      indexer=other.indexer,
      public_node=other.public_node,
      private_node=other.private_node,
      streams=other.streams,
      settings=other.settings,
      perpetual_market=other.perpetual_market,
      subaccount=other.subaccount,
      depth=Depth.of(other),
      funding=Funding.of(other),
      index=Index.of(other),
      rules=Rules.of(other),
    )
