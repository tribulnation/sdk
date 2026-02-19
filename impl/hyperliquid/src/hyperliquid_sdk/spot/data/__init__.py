from dataclasses import dataclass as _dataclass

from trading_sdk.market import MarketData as _MarketData
from hyperliquid import Hyperliquid as _Hyperliquid
from hyperliquid_sdk.spot.core import Meta, SpotMixin
from .depth import Depth
from .rules import Rules

@_dataclass(frozen=True)
class MarketData(SpotMixin, _MarketData):
  Depth = Depth
  Rules = Rules
  depth: Depth
  rules: Rules

  @classmethod
  def of(cls, *, address: str, client: _Hyperliquid, validate: bool = True, meta: Meta):
    return cls(
      address=address, client=client, validate=validate, meta=meta,
      depth=Depth(address=address, client=client, validate=validate, meta=meta),
      rules=Rules(address=address, client=client, validate=validate, meta=meta),
    )