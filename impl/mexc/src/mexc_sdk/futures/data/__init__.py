from dataclasses import dataclass as _dataclass

from mexc import MEXC


from trading_sdk.market import PerpMarketData as _PerpMarketData
from mexc_sdk.core import PerpMixin, Settings
from .rules import Rules
from .depth import Depth
from .funding import Funding
from .index import Index

@_dataclass(frozen=True)
class MarketData(PerpMixin, _PerpMarketData):
  rules: Rules
  depth: Depth
  funding: Funding
  index: Index

  @classmethod
  def of(cls, meta: PerpMixin.Meta, *, client: MEXC, settings: Settings = {}):
    return cls(
      meta=meta, client=client, settings=settings,
      rules=Rules.of(meta=meta, client=client, settings=settings),
      depth=Depth.of(meta=meta, client=client, settings=settings),
      funding=Funding.of(meta=meta, client=client, settings=settings),
      index=Index.of(meta=meta, client=client, settings=settings),
    )
