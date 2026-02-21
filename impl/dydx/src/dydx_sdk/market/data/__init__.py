from dataclasses import dataclass as _dataclass

from trading_sdk.market import PerpMarketData
from dydx_sdk.core import Mixin as _Mixin
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
  def of(cls, base: _Mixin):
    return cls(
      depth=Depth.of(base),
      funding=Funding.of(base),
      index=Index.of(base),
      rules=Rules.of(base)
    )
