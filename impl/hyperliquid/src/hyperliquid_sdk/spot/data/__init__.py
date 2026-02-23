from dataclasses import dataclass as _dataclass

from trading_sdk.market import MarketData as _MarketData
from hyperliquid_sdk.spot.core import SpotMixin
from .depth import Depth
from .rules import Rules

@_dataclass(frozen=True)
class MarketData(SpotMixin, _MarketData):
  Depth = Depth
  Rules = Rules
  depth: Depth
  rules: Rules

  @classmethod
  def of(cls, other: 'SpotMixin'):
    return cls(
      address=other.address,
      client=other.client,
      settings=other.settings,
      streams=other.streams,
      meta=other.meta,
      depth=Depth.of(other),
      rules=Rules.of(other),
    )