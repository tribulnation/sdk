from dataclasses import dataclass as _dataclass

from trading_sdk.market import PerpMarketData
from hyperliquid_sdk.perps.core import PerpMixin
from .depth import Depth
from .funding import Funding
from .index import Index
from .rules import Rules

@_dataclass(frozen=True)
class MarketData(PerpMixin, PerpMarketData):
  Depth = Depth
  Funding = Funding
  Index = Index
  Rules = Rules
  depth: Depth
  funding: Funding
  index: Index
  rules: Rules

  @classmethod
  def of(cls, other: 'PerpMixin'):
    return cls(
      address=other.address,
      client=other.client,
      settings=other.settings,
      streams=other.streams,
      meta=other.meta,
      depth=Depth.of(other),
      funding=Funding.of(other),
      index=Index.of(other),
      rules=Rules.of(other),
    )