from dataclasses import dataclass as _dataclass

from trading_sdk.market import PerpMarketData
from hyperliquid import Hyperliquid as _Hyperliquid
from hyperliquid_sdk.perps.core import Meta, PerpMixin
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
  def of(cls, *, address: str, client: _Hyperliquid, validate: bool = True, meta: Meta):
    return cls(
      address=address, client=client, validate=validate, meta=meta,
      depth=Depth(address=address, client=client, validate=validate, meta=meta),
      funding=Funding(address=address, client=client, validate=validate, meta=meta),
      index=Index(address=address, client=client, validate=validate, meta=meta),
      rules=Rules(address=address, client=client, validate=validate, meta=meta),
    )