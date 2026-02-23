from dataclasses import dataclass as _dataclass

from mexc import MEXC


from trading_sdk.market import PerpMarketData as _PerpMarketData
from mexc_sdk.core import PerpMixin, Settings, StreamManager
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
  def of(cls, meta: PerpMixin.Meta, *, client: MEXC, settings: Settings = {}, streams: dict[str, StreamManager] = {}):
    return cls(
      meta=meta, client=client, settings=settings, streams=streams,
      rules=Rules.of(meta=meta, client=client, settings=settings, streams=streams),
      depth=Depth.of(meta=meta, client=client, settings=settings, streams=streams),
      funding=Funding.of(meta=meta, client=client, settings=settings, streams=streams),
      index=Index.of(meta=meta, client=client, settings=settings, streams=streams),
    )
